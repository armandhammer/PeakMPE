/* LCD cache: a character the display already shows is not sent again (v0.23).
 *
 * Every LCD write keeps the main loop busy: one character is three SPI bytes at
 * PCLK1/64, about 51 us, busy-waited (findings, "LCD bus speed"), and the
 * 1 kHz modulation tick is not caught up, so a pass longer than 1 ms loses
 * ticks. Stock redraws whole rows: a knob event rewrites the parameter name and
 * both value rows although one to three characters change (34 data writes, 33
 * of them leaving the cell as it was; the patch's bar row made it 68, emulated,
 * work/_overlay_writes.py). On the synth about half the ticks were lost while
 * a knob turned (series M7, observed).
 *
 * All text reaches the display through two calls in stock's escape layer:
 * 0x0800D1FA (lcd_putc, one character) and 0x0800D216 (lcd_cursor, from the
 * cursor escape 09 col row). The only other writers are lcd_init (boot: reset,
 * CGRAM, clear), the display on/off commands (0x0C/0x08, the screen saver) and
 * this patch's own custom-character loads (disp.c). So a copy of the display's
 * 128 DDRAM cells kept at those two calls is exact:
 *
 *  - lcd_cache_cursor only records where the next character goes;
 *  - lcd_cache_putc compares the character with the copy; an equal one only
 *    moves the position on, a different one sends the cursor command when the
 *    display's own address isn't there already, then the character;
 *  - code 8 (clear) goes through and the copy becomes spaces.
 *
 * Cells the copy doesn't know hold 0xFF, a code lcd_putc never sends, so they
 * are always written. The copy starts unknown (it checks a magic word, so it
 * doesn't depend on when the patch's RAM is set up), becomes spaces after
 * lcd_init's clear, and becomes unknown again when the display is powered up
 * after the screen saver (0x08016932): if the panel lost its RAM there, the
 * next draw writes every character, as stock would. A cursor address of 0x80
 * or more (stock's command would then be another command) goes to stock as it
 * is and forgets the copy.
 *
 * Main loop only, as stock's escape state is.
 */

#include "mpe.h"

#define CELLS 0x80
#define COLS 20
#define UNKNOWN 0xFF
#define MAGIC 0x4C434443u   /* "LCDC" */

uint32_t lcd_cache_spills;  /* writes past column 19 (tests read it) */
static uint32_t magic;
static uint8_t cell[CELLS];
static uint8_t want;        /* where the next character goes */
static uint8_t want_known;  /* 0: no cursor set since the copy was lost */
static uint8_t ac;          /* the display's own DDRAM address */
static uint8_t ac_known;

static void forget(void)
{
    for (uint32_t i = 0; i < CELLS; i++)
        cell[i] = UNKNOWN;
    want_known = 0;
    ac_known = 0;
    magic = MAGIC;
}

static void ready(void)
{
    if (magic != MAGIC)
        forget();
}

static void blank(void)
{
    for (uint32_t i = 0; i < CELLS; i++)
        cell[i] = ' ';
    want = ac = 0;
    want_known = ac_known = 1;
    magic = MAGIC;
}

/* The DDRAM code lcd_putc (0x080168C8) writes for c, CLEAR for code 8, NONE
 * when it writes nothing. Same tests, same order, on the full register. */
#define NONE 0x100
#define CLEAR 0x101
static uint32_t code_of(uint32_t c)
{
    if (c == 0xBA)
        return ' ';
    if ((uint8_t)(c + 0x45) <= 4)
        return (uint8_t)(0x95 - c);
    if (c <= 7)
        return c;
    if ((uint8_t)(c - 0x10) <= 0x6F)
        return (uint8_t)c;      /* lcd_write_data sends the low byte */
    if (c == 8)
        return CLEAR;
    if (c == 0x1F)
        return 0x1F;
    return NONE;
}

/* 0x0800D1FA: the escape layer's call of lcd_putc. */
void lcd_cache_putc(uint32_t c)
{
    ready();
    uint32_t k = code_of(c);
    if (k == NONE)
        return;
    if (k == CLEAR) {
        lcd_putc(c);
        blank();
        return;
    }
    if (!want_known) {          /* where it lands isn't known: write it, forget the copy */
        lcd_putc(c);
        forget();
        return;
    }
    if ((want & 0x1F) >= COLS) {
        /* Past the 20 visible columns: whether the controller steps on to
         * the hidden cells or to the next row isn't known, so the character
         * is written at its address and the copy is forgotten. Counted for
         * the tests (none seen in stock's pages so far). */
        if (!ac_known || ac != want)
            lcd_write_cmd(0x80 | want);
        lcd_putc(c);
        lcd_cache_spills++;
        forget();
        return;
    }
    if (cell[want] != k) {
        if (!ac_known || ac != want)
            lcd_write_cmd(0x80 | want);
        lcd_putc(c);
        cell[want] = (uint8_t)k;
        ac = (uint8_t)((want + 1) & (CELLS - 1));
        ac_known = 1;
    }
    want = (uint8_t)((want + 1) & (CELLS - 1));
}

/* 0x0800D216: the escape layer's call of lcd_cursor (col, row). Also the
 * patch's own cursor moves (disp.c, qassign.c). */
void lcd_cache_cursor(uint32_t col, uint32_t row)
{
    ready();
    uint32_t a = (col + (row << 5)) & 0xFF;     /* as lcd_cursor: uxtb, then eor 0x80 */
    if (a >= CELLS) {
        lcd_cursor(col, row);
        forget();
        return;
    }
    want = (uint8_t)a;
    want_known = 1;
}

/* 0x0800D202: the boot's lcd_init, which ends with a clear. */
void lcd_cache_init(void)
{
    lcd_init();
    blank();
}

/* 0x08016932: lcd_display_on's panel power-up (the screen saver ends). */
void lcd_cache_power_on(void)
{
    lcd_power_on();
    forget();
}

/* The patch wrote the CGRAM or sent its own address command (disp.c): the
 * display's address is no longer where the copy thinks. */
void lcd_cache_lost_ac(void)
{
    ready();
    ac_known = 0;
}

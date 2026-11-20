/* Peak patch dump on patch change (v0.30; docs/peak-features.md, Later).
 *
 * Settings PATCH DUMP > Send = USB: whenever a stored patch is loaded (a
 * program change, the panel's patch buttons, a cued patch), the Peak sends
 * the new current patch over USB in the editor's own format, the message
 * stock sends when an editor asks for the current patch (request 40, answer
 * 00; findings, "The editor protocol"). An editor or DAW that keeps the
 * patch can stay in step without asking.
 *
 *  - The hook is stock's patch_select_load (0x0801AF78) call of
 *    patch_select_set (0x0801AFC2), made right after the stored patch was
 *    loaded; Compare, Initialise and a patch received by SysEx (the editor's
 *    own write included) don't pass there, so nothing is echoed back.
 *  - The power-up load (settings_load, before the main loop) sends nothing:
 *    the main loop's first pass arms this.
 *  - The message is stock's: editor_patch_request(0) puts the main loop's
 *    SysEx reply state on "current patch, port 0" (USB; any other port is
 *    DIN), and sysex_rx_poll sends it on its next pass. While another
 *    answer is being sent (a bank dump takes seconds) the dump waits for it.
 */

#include "mpe.h"

#define SYSEX_REPLY_STATE 0x67C   /* sysex_state: 0 = nothing being answered */
#define PORT_USB 0

static uint8_t running;           /* the main loop has passed: not the power-up load */
static uint8_t pending;

int pdump_on(void)
{
    return globals[MPE_G_PDUMP] == 1;
}

static void try_send(void)
{
    if (sysex_state[SYSEX_REPLY_STATE])
        return;                   /* stock is answering something: next tick */
    editor_patch_request(PORT_USB);
    pending = 0;
}

/* Replaces patch_select_load's call of patch_select_set (0x0801AFC2). */
void pdump_patch_selected(uint8_t number, uint8_t bank)
{
    patch_select_set(number, bank);
    if (!running || !pdump_on())
        return;
    pending = 1;
    try_send();
}

/* Once per 1 kHz tick from the main loop (mpe_ui_poll). */
void pdump_poll(void)
{
    running = 1;
    if (pending && !pdump_on())
        pending = 0;              /* Send turned Off while it waited (review 2026-11-20) */
    if (pending)
        try_send();
}

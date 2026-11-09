// Prepare a raw STM32 flash image for analysis: add RAM and peripheral
// blocks, and create functions at every vector-table handler so auto-analysis
// has entry points to follow.
//
// Run as a headless -preScript (see scripts/ghidra-import.sh).
// @category SummitMPE

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;

public class SetupCortexM extends GhidraScript {

    // STM32F42x/F43x map; the CPU is confirmed for Peak only (see docs/firmware-format.md).
    private static final Object[][] BLOCKS = {
        {"CCMRAM", 0x10000000L, 0x10000L, false},
        {"SRAM", 0x20000000L, 0x30000L, false},
        {"PERIPH", 0x40000000L, 0x20000000L, true},
        {"FMC", 0x60000000L, 0x40000000L, true},
        {"SCS", 0xE0000000L, 0x100000L, true},
    };

    // Cortex-M4 has 16 system exceptions; STM32F429 adds 91 IRQs.
    private static final int VECTORS = 16 + 91;

    @Override
    protected void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        for (Object[] b : BLOCKS) {
            Address start = toAddr((Long) b[1]);
            if (mem.getBlock(start) != null) {
                continue;
            }
            MemoryBlock block = mem.createUninitializedBlock((String) b[0], start, (Long) b[2], false);
            block.setRead(true);
            block.setWrite(true);
            block.setExecute(false);
            block.setVolatile((Boolean) b[3]);
        }

        // The raw image is the only initialized block; its start is the load base.
        MemoryBlock flash = null;
        for (MemoryBlock b : mem.getBlocks()) {
            if (b.isInitialized()) {
                flash = b;
                break;
            }
        }
        if (flash == null) {
            throw new IllegalStateException("no initialized block (raw image) found");
        }
        flash.setExecute(true);
        // Read-only flash lets the decompiler fold literal-pool loads into
        // constants (pointers show as addresses, not DAT_ references).
        flash.setWrite(false);
        Address base = flash.getStart();
        long flashEnd = flash.getEnd().getOffset() + 1;
        int created = 0;
        for (int i = 1; i < VECTORS; i++) {
            Address slot = base.add(i * 4L);
            createDWord(slot);
            long target = mem.getInt(slot) & 0xFFFFFFFFL;
            if ((target & 1) == 0 || target < base.getOffset() || target >= flashEnd) {
                continue;
            }
            Address entry = toAddr(target & ~1L);
            String name = i == 1 ? "Reset_Handler" : String.format("vector_%d_%08x", i, entry.getOffset());
            if (getFunctionAt(entry) == null) {
                disassemble(entry);
                createFunction(entry, null);
                created++;
            }
            if (i == 1 || getSymbolAt(entry) == null || getSymbolAt(entry).getSource() == SourceType.DEFAULT) {
                createLabel(entry, name, true, SourceType.ANALYSIS);
            }
        }
        createDWord(base);
        createLabel(base, "vector_table", true, SourceType.ANALYSIS);
        println("SetupCortexM: blocks added, " + created + " vector handlers created");
    }
}

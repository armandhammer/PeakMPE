// Write the decompiled C of the functions containing the given addresses.
//
//   analyzeHeadless ... -process -noanalysis -postScript DecompileAt.java OUT_DIR 0x0801d9bc ...
//
// Each function goes to OUT_DIR/<entry>.c; the paths are printed.
// @category SummitMPE

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DecompileAt extends GhidraScript {

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        out.mkdirs();
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        try {
            for (int i = 1; i < args.length; i++) {
                Address addr = toAddr(Long.decode(args[i]));
                Function fn = getFunctionContaining(addr);
                if (fn == null) {
                    disassemble(addr);
                    fn = createFunction(addr, null);
                }
                if (fn == null) {
                    println("DECOMPILE no function at " + addr);
                    continue;
                }
                DecompileResults res = decomp.decompileFunction(fn, 60, monitor);
                File file = new File(out, fn.getEntryPoint().toString() + ".c");
                try (PrintWriter w = new PrintWriter(file)) {
                    w.println("// " + fn.getName() + " @ " + fn.getEntryPoint() + " (" + currentProgram.getName() + ")");
                    w.println(res.decompileCompleted() ? res.getDecompiledFunction().getC()
                        : "// failed: " + res.getErrorMessage());
                }
                println("DECOMPILE " + file.getPath());
            }
        } finally {
            decomp.dispose();
        }
    }
}

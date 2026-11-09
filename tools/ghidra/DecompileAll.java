// Write every function's decompiled C to one file, each headed by its callers,
// so the whole program can be searched with grep.
//
//   analyzeHeadless ... -process -noanalysis -postScript DecompileAll.java OUT_FILE
//
// @category SummitMPE

import java.io.File;
import java.io.PrintWriter;
import java.util.Set;
import java.util.TreeSet;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class DecompileAll extends GhidraScript {

    @Override
    protected void run() throws Exception {
        File out = new File(getScriptArgs()[0]);
        out.getParentFile().mkdirs();
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        int count = 0;
        try (PrintWriter w = new PrintWriter(out)) {
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext() && !monitor.isCancelled()) {
                Function fn = it.next();
                Set<String> callers = new TreeSet<>();
                for (Function c : fn.getCallingFunctions(monitor)) {
                    callers.add(c.getEntryPoint().toString());
                }
                w.println("////// " + fn.getName() + " @ " + fn.getEntryPoint()
                    + " callers: " + String.join(" ", callers));
                DecompileResults res = decomp.decompileFunction(fn, 60, monitor);
                w.println(res.decompileCompleted() ? res.getDecompiledFunction().getC()
                    : "// failed: " + res.getErrorMessage());
                count++;
            }
        } finally {
            decomp.dispose();
        }
        println("DECOMPILE_ALL " + count + " functions -> " + out.getPath());
    }
}

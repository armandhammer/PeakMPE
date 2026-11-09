// Apply a symbols CSV (address,name,kind,confidence,notes) to the program:
// functions are created where missing and named; data addresses are labelled.
// The notes column becomes a plate comment.
//
//   analyzeHeadless ... -process -postScript ApplySymbols.java docs/symbols/summit-2.2-2121.csv
//
// @category SummitMPE

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class ApplySymbols extends GhidraScript {

    @Override
    protected void run() throws Exception {
        List<String> lines = Files.readAllLines(Paths.get(getScriptArgs()[0]));
        int applied = 0;
        for (String line : lines.subList(1, lines.size())) {
            if (line.isBlank()) {
                continue;
            }
            String[] f = line.split(",", 5);
            Address addr = toAddr(Long.decode(f[0]));
            String name = f[1];
            String note = f.length > 4 ? f[4] : "";
            if (f[2].equals("function")) {
                Function fn = getFunctionAt(addr);
                if (fn == null) {
                    disassemble(addr);
                    fn = createFunction(addr, name);
                }
                if (fn != null) {
                    fn.setName(name, SourceType.USER_DEFINED);
                }
            } else {
                createLabel(addr, name, true, SourceType.USER_DEFINED);
            }
            if (!note.isEmpty()) {
                setPlateComment(addr, "[" + f[3] + "] " + note);
            }
            applied++;
        }
        println("ApplySymbols: " + applied + " symbols");
    }
}

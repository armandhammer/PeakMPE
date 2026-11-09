// Parity with the Python build (only with Novation's firmware in firmware/; skipped without it).
//
// Runs the TS patcher under Node on firmware/summit-firmware-2.2-build2121.syx
// and compares its output byte for byte with tools/patch.py's .syx for the
// same definition. Skipped, with the reason printed, when the official file
// or a Python that can run tools/patch.py (and the ARM toolchain it calls)
// is missing. Python: $SUMMIT_PYTHON, else ../.venv/bin/python, else python3.
// $SUMMIT_FIRMWARE_DIR overrides where the official file is looked for.

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseDescriptor } from "../src/core/descriptor";
import { sha256 } from "../src/core/hash";
import { patchFirmware } from "../src/core/patcher";
import { FakeSummit } from "../src/flash/fake";
import { flash, Plan, TIMING } from "../src/flash/protocol";
import raw from "../patches/mpe.json";

const ROOT = resolve(__dirname, "..", "..");
const d = parseDescriptor(raw);
const FIRMWARE_DIR = process.env.SUMMIT_FIRMWARE_DIR ?? join(ROOT, "firmware");
const FIRMWARE = join(FIRMWARE_DIR, d.input.fileName);

function python(): string | null {
  for (const p of [process.env.SUMMIT_PYTHON, join(ROOT, ".venv", "bin", "python"), "python3"]) {
    if (!p) continue;
    try {
      execFileSync(p, ["-I", "-c", "import sys"], { stdio: "ignore" });
      return p;
    } catch {
      /* try the next one */
    }
  }
  return null;
}

const py = python();
const reason = !existsSync(FIRMWARE)
  ? `${FIRMWARE} not present (run scripts/fetch-firmware.sh)`
  : !py
    ? "no Python found (set SUMMIT_PYTHON)"
    : null;
if (reason) console.warn(`parity test skipped: ${reason}`);

describe.skipIf(reason !== null)("parity with tools/patch.py", () => {
  it("TS output is byte-identical to patch.py's .syx", async () => {
    const out = mkdtempSync(join(tmpdir(), "summit-parity-"));
    try {
      execFileSync(py!, ["-I", join(ROOT, "tools", "patch.py"), join(ROOT, d.built.definition),
        "--firmware", FIRMWARE_DIR, "--out", out], { cwd: ROOT, stdio: "pipe" });
      const pyOut = readFileSync(join(out, d.output.fileName));
      const ts = await patchFirmware(new Uint8Array(readFileSync(FIRMWARE)), d);
      expect(ts.syx.length).toBe(pyOut.length);
      expect(Buffer.from(ts.syx).equals(pyOut)).toBe(true);
      expect(ts.sha256).toBe(await sha256(new Uint8Array(pyOut)));
      expect(ts.sha256).toBe("28916b05a90e56f8091644031af03b01d1f7e10b0160ac2e6e1017ad8c08ac96");
    } finally {
      rmSync(out, { recursive: true, force: true });
    }
  });

  it("the patched and the official file flash unchanged to the fake bootloader", async () => {
    const official = new Uint8Array(readFileSync(FIRMWARE));
    const patched = (await patchFirmware(official, d)).syx;
    const fast = { ...TIMING, settleAfterBootloader: 0, identityTimeout: 50, poll: 5 };
    for (const data of [patched, official]) {
      const synth = new FakeSummit({ repeatEvery: 40 });
      const r = await flash(new Plan(data), synth, { confirm: async () => true }, fast);
      expect(Buffer.concat(synth.received).equals(Buffer.from(data))).toBe(true);
      expect(r.messagesSent).toBe(data === patched ? d.output.messages : 8719);
      expect(r.version).toBe("2126");
    }
  });
});

import { describe, expect, it } from "vitest";
import { parseDescriptor } from "../src/core/descriptor";
import { identifyFile, PatchError, patchFirmware } from "../src/core/patcher";
import { b64, fakeSetup } from "./fixtures";
import committed from "../patches/mpe.json";

describe("patcher", () => {
  it("builds the expected file from the official one", async () => {
    const { official, out, d } = await fakeSetup();
    const r = await patchFirmware(official, d);
    expect(r.syx).toEqual(out);
    expect(r.fileName).toBe("fake+mod.syx");
  });

  it("refuses any other input", async () => {
    const { official, d } = await fakeSetup();
    const other = official.slice();
    other[100] ^= 1;
    await expect(patchFirmware(other, d)).rejects.toThrow(PatchError);
  });

  it("refuses when the result differs from the expected hash", async () => {
    const { official, d } = await fakeSetup();
    d.writes[0].data = b64([0xaa, 0xbc]);
    await expect(patchFirmware(official, d)).rejects.toThrow(/does not match the expected result/);
  });

  it("refuses writes outside the image", async () => {
    const { official, d } = await fakeSetup();
    d.writes[1].address = "0x0900F000";
    await expect(patchFirmware(official, d)).rejects.toThrow(/outside the image/);
  });

  it("tells official, patched and unknown files apart", async () => {
    const { official, out, d } = await fakeSetup();
    expect((await identifyFile(official, d)).kind).toBe("official");
    expect((await identifyFile(out, d)).kind).toBe("patched");
    expect((await identifyFile(new Uint8Array(3), d)).kind).toBe("unknown");
  });

  it("accepts the committed MPE descriptor", () => {
    const d = parseDescriptor(committed);
    expect(d.input.sha256).toBe("83b28931293647f2b4bfcf524c6875d3845468e6f0c037641c4318e3d249396f");
    expect(d.output.sha256).toBe("28916b05a90e56f8091644031af03b01d1f7e10b0160ac2e6e1017ad8c08ac96");
    expect(() => parseDescriptor({ ...committed, formatVersion: 2 })).toThrow();
  });
});

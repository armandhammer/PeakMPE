import { describe, expect, it } from "vitest";
import { sha256 } from "../src/core/hash";
import { decode, encode, messages, pack, SyxError, unpack } from "../src/core/syx";

const hex = (b: Uint8Array) => Buffer.from(b).toString("hex");

describe("syx codec", () => {
  // Vectors from tools/syx.py.
  it("packs like tools/syx.py", () => {
    expect(hex(pack(Uint8Array.from({ length: 32 }, (_, i) => i)))).toBe(
      "0000202018100a0603420110502c180d07036201084826140a4542714064341b0e07236178");
    expect(hex(pack(new Uint8Array(32).fill(0xff)))).toBe("7f".repeat(36) + "78");
  });

  it("encodes a file like tools/syx.py", async () => {
    const img = Uint8Array.from({ length: 160 }, (_, i) => (i * 7 + 3) & 0xff);
    const d = encode(Uint8Array.from([1, 0x33, 0, 0, 2, 1, 2, 6]), img);
    expect(d.length).toBe(235);
    expect(await sha256(d)).toBe("952ae69b1a1f5a890a97a3d52125f874e33a90dd6550b5bf820e434fe879366c");
  });

  it("round-trips random blocks", () => {
    for (let t = 0; t < 200; t++) {
      const b = Uint8Array.from({ length: 32 }, () => Math.floor(Math.random() * 256));
      expect(unpack(pack(b))).toEqual(b);
    }
  });

  it("sends the vector block last and decodes back", () => {
    const img = Uint8Array.from({ length: 96 }, (_, i) => i);
    const file = encode(Uint8Array.from([1, 2]), img);
    expect(messages(file).map((m) => m.cmd)).toEqual([0x71, 0x72, 0x72, 0x73]);
    const { header, image } = decode(file);
    expect(header).toEqual(Uint8Array.from([1, 2]));
    expect(image).toEqual(img);
  });

  it("rejects non-zero padding, bit 7, FPGA files and junk", () => {
    const s = pack(new Uint8Array(32));
    s[36] = 0x01;
    expect(() => unpack(s)).toThrow(SyxError);
    s[36] = 0x80;
    expect(() => unpack(s)).toThrow(SyxError);
    expect(() => decode(Uint8Array.from([0xf0, 0, 0x20, 0x29, 0, 0x7c, 1, 0xf7]))).toThrow(/FPGA/);
    expect(() => decode(Uint8Array.from([0x41, 0x42]))).toThrow(SyxError);
    expect(() => decode(Uint8Array.from([0xf0, 0x43, 0, 0, 0, 0x71, 0xf7]))).toThrow(/non-Novation/);
  });
});

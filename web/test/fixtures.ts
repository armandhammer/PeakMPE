// A synthetic "firmware" and descriptor, so the patcher and flasher can be
// tested without Novation's file (CI never has it).

import type { Descriptor } from "../src/core/descriptor";
import { IMAGE_BASE } from "../src/core/descriptor";
import { sha256 } from "../src/core/hash";
import { encode } from "../src/core/syx";

export const HEADER = Uint8Array.from([0x01, 0x33, 0x00, 0x00, 0x02, 0x01, 0x02, 0x06]);

export function fakeImage(blocks = 40): Uint8Array {
  return Uint8Array.from({ length: 32 * blocks }, (_, i) => (i * 7 + 3) & 0xff);
}

export function b64(bytes: number[]): string {
  return btoa(String.fromCharCode(...bytes));
}

/** Official fake file, the patched file, and a descriptor connecting them. */
export async function fakeSetup() {
  const image = fakeImage();
  const official = encode(HEADER, image);
  const patched = new Uint8Array(image.length + 64).fill(0xff);
  patched.set(image);
  patched.set([0xaa, 0xbb], 0x40);
  patched.set([1, 2, 3, 4, 5], image.length + 3);
  const out = encode(HEADER, patched);
  const d: Descriptor = {
    format: "summit-mpe-patch-descriptor",
    formatVersion: 1,
    name: "fake",
    title: "Fake",
    version: "0",
    label: "",
    summary: "",
    built: { commit: null, definition: "test" },
    input: { fileName: "fake.syx", sha256: await sha256(official), bytes: official.length,
      imageSha256: await sha256(image), imageLength: image.length },
    output: { fileName: "fake+mod.syx", sha256: await sha256(out), bytes: out.length,
      imageSha256: await sha256(patched), imageLength: patched.length, messages: patched.length / 32 + 1 },
    header: null,
    fill: 0xff,
    writes: [
      { address: `0x${(IMAGE_BASE + 0x40).toString(16).toUpperCase()}`, data: b64([0xaa, 0xbb]), why: "a" },
      { address: `0x${(IMAGE_BASE + image.length + 3).toString(16).toUpperCase()}`, data: b64([1, 2, 3, 4, 5]), why: "b" },
    ],
  };
  return { image, official, patched, out, d };
}

// Apply a descriptor to the user's official firmware file, with every check
// the web app relies on. Nothing is offered for download or flashing unless
// patchFirmware() returned without throwing.

import { base64ToBytes, hexToBytes, sha256 } from "./hash";
import { type Descriptor, IMAGE_BASE } from "./descriptor";
import { decode, encode } from "./syx";

export type IdentifyResult =
  | { kind: "official"; sha256: string }
  | { kind: "patched"; sha256: string }
  | { kind: "unknown"; sha256: string };

export class PatchError extends Error {}

/** Which known file this is: the official input, our own output, or neither. */
export async function identifyFile(data: Uint8Array, d: Descriptor): Promise<IdentifyResult> {
  const h = await sha256(data);
  if (h === d.input.sha256) return { kind: "official", sha256: h };
  if (h === d.output.sha256) return { kind: "patched", sha256: h };
  return { kind: "unknown", sha256: h };
}

export interface PatchResult {
  syx: Uint8Array;
  sha256: string;
  fileName: string;
}

/**
 * official .syx -> patched .syx. Throws PatchError unless the input is the
 * exact official file and the output matches the descriptor's hashes.
 */
export async function patchFirmware(official: Uint8Array, d: Descriptor): Promise<PatchResult> {
  const inHash = await sha256(official);
  if (inHash !== d.input.sha256)
    throw new PatchError(`this is not the official ${d.input.fileName} (SHA-256 ${inHash})`);
  const { header, image } = decode(official);
  if (image.length !== d.input.imageLength || (await sha256(image)) !== d.input.imageSha256)
    throw new PatchError("the decoded firmware image does not match the expected one");

  const out = new Uint8Array(d.output.imageLength).fill(d.fill);
  out.set(image, 0);
  for (const w of d.writes) {
    const off = parseInt(w.address, 16) - IMAGE_BASE;
    const data = base64ToBytes(w.data);
    if (off < 0 || off + data.length > out.length) throw new PatchError(`write at ${w.address} is outside the image`);
    out.set(data, off);
  }
  if ((await sha256(out)) !== d.output.imageSha256)
    throw new PatchError("the patched image does not match the expected result; refusing to continue");

  const syx = encode(d.header === null ? header : hexToBytes(d.header), out);
  const outHash = await sha256(syx);
  if (outHash !== d.output.sha256 || syx.length !== d.output.bytes)
    throw new PatchError("the patched file does not match the expected result; refusing to continue");
  return { syx, sha256: outHash, fileName: d.output.fileName };
}

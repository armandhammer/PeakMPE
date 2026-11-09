// The patch descriptor written by tools/web_descriptor.py (docs/web.md).
// It holds only our own bytes; the official firmware appears only as hashes.

export interface FileInfo {
  fileName: string;
  sha256: string;
  bytes: number;
  imageSha256: string;
  imageLength: number;
}

export interface Write {
  /** Flash address, "0x0800D0F2". */
  address: string;
  /** Base64 of the bytes written there. */
  data: string;
  why: string;
}

export interface Descriptor {
  format: "summit-mpe-patch-descriptor";
  formatVersion: 1;
  name: string;
  title: string;
  version: string;
  label: string;
  summary: string;
  built: { commit: string | null; definition: string };
  input: FileInfo;
  output: FileInfo & { messages: number };
  /** null: keep the official 0x71 header; else the new header body as hex. */
  header: string | null;
  fill: number;
  writes: Write[];
}

export const IMAGE_BASE = 0x0800c000;
export const FLASH_LIMIT = 0x08060000;

/** Structural check of untrusted JSON before it is used. */
export function parseDescriptor(json: unknown): Descriptor {
  const d = json as Descriptor;
  const hex64 = /^[0-9a-f]{64}$/;
  const ok =
    d &&
    d.format === "summit-mpe-patch-descriptor" &&
    d.formatVersion === 1 &&
    hex64.test(d.input?.sha256) &&
    hex64.test(d.input?.imageSha256) &&
    hex64.test(d.output?.sha256) &&
    hex64.test(d.output?.imageSha256) &&
    Number.isInteger(d.output.imageLength) &&
    d.output.imageLength >= d.input.imageLength &&
    IMAGE_BASE + d.output.imageLength <= FLASH_LIMIT &&
    Array.isArray(d.writes) &&
    d.writes.every((w) => /^0x[0-9A-Fa-f]{8}$/.test(w.address) && typeof w.data === "string") &&
    (d.header === null || /^([0-9a-f]{2})+$/.test(d.header));
  if (!ok) throw new Error("patch descriptor is malformed or of an unknown format");
  return d;
}

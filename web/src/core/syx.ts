// Novation Summit/Peak firmware update (.syx) codec: a port of tools/syx.py.
// Format: docs/firmware-format.md.
//
//   F0 00 20 29 00 71 <header> F7        product id, version digits
//   F0 00 20 29 00 72 <37 septets> F7    32 image bytes each, from image offset 0x20
//   F0 00 20 29 00 73 <37 septets> F7    image bytes 0x00-0x1F, sent last

export const CMD_HEADER = 0x71;
export const CMD_DATA = 0x72;
export const CMD_FINAL = 0x73;
export const BLOCK = 32;
export const SEPTETS = 37;
const NOVATION = [0x00, 0x20, 0x29];

export class SyxError extends Error {}

export interface Message {
  cmd: number;
  body: Uint8Array;
  /** The whole message, F0 ... F7. */
  raw: Uint8Array;
}

/** Split a file into its Novation SysEx messages, in file order. */
export function messages(data: Uint8Array): Message[] {
  const out: Message[] = [];
  let pos = 0;
  while (pos < data.length) {
    if (data[pos] !== 0xf0) throw new SyxError(`expected F0 at offset 0x${pos.toString(16)}`);
    const end = data.indexOf(0xf7, pos);
    if (end < 0) throw new SyxError(`unterminated SysEx message at offset 0x${pos.toString(16)}`);
    const msg = data.subarray(pos + 1, end);
    if (msg.length < 5 || msg[0] !== NOVATION[0] || msg[1] !== NOVATION[1] || msg[2] !== NOVATION[2] || msg[3] !== 0)
      throw new SyxError(`non-Novation message at offset 0x${pos.toString(16)}`);
    out.push({ cmd: msg[4], body: msg.subarray(5), raw: data.subarray(pos, end + 1) });
    pos = end + 1;
  }
  return out;
}

/** 37 septets (big-endian 7-bit bitstream) -> 32 bytes; the 3 padding bits must be zero. */
export function unpack(septets: Uint8Array): Uint8Array {
  if (septets.length !== SEPTETS) throw new SyxError(`block has ${septets.length} septets, expected ${SEPTETS}`);
  const out = new Uint8Array(BLOCK);
  let acc = 0;
  let n = 0;
  let k = 0;
  for (const b of septets) {
    if (b & 0x80) throw new SyxError("data byte with bit 7 set");
    acc = ((acc << 7) | b) & 0x7fff; // never more than 14 bits are pending
    n += 7;
    if (n >= 8 && k < BLOCK) {
      n -= 8;
      out[k++] = (acc >> n) & 0xff;
    }
  }
  if (k !== BLOCK || (acc & ((1 << n) - 1)) !== 0)
    throw new SyxError("block does not carry exactly 32 bytes with zero padding");
  return out;
}

/** 32 bytes -> 37 septets. */
export function pack(block: Uint8Array): Uint8Array {
  if (block.length !== BLOCK) throw new SyxError("block must be 32 bytes");
  const out = new Uint8Array(SEPTETS);
  let acc = 0;
  let n = 0;
  let k = 0;
  for (const b of block) {
    acc = ((acc << 8) | b) & 0x7fff;
    n += 8;
    while (n >= 7) {
      n -= 7;
      out[k++] = (acc >> n) & 0x7f;
    }
  }
  out[k] = (acc << (7 - n)) & 0x7f; // the last n bits plus zero padding
  return out;
}

export function frame(cmd: number, body: Uint8Array): Uint8Array {
  const out = new Uint8Array(body.length + 7);
  out.set([0xf0, ...NOVATION, 0x00, cmd]);
  out.set(body, 6);
  out[out.length - 1] = 0xf7;
  return out;
}

export interface Decoded {
  header: Uint8Array;
  image: Uint8Array;
}

/** A firmware file -> its 0x71 header body and flat image (vector table first). */
export function decode(data: Uint8Array): Decoded {
  const msgs = messages(data);
  let header: Uint8Array | null = null;
  let final: Uint8Array | null = null;
  const blocks: Uint8Array[] = [];
  for (const m of msgs) {
    if (m.cmd === CMD_HEADER) header = m.body;
    else if (m.cmd === CMD_DATA) blocks.push(unpack(m.body));
    else if (m.cmd === CMD_FINAL) final = unpack(m.body);
    else throw new SyxError(`command 0x${m.cmd.toString(16)} is not a firmware image (FPGA file?)`);
  }
  if (header === null || final === null) throw new SyxError("missing header (0x71) or final block (0x73)");
  const image = new Uint8Array(BLOCK * (blocks.length + 1));
  image.set(final, 0);
  blocks.forEach((b, i) => image.set(b, BLOCK * (i + 1)));
  return { header: header.slice(), image };
}

export function encode(header: Uint8Array, image: Uint8Array): Uint8Array {
  if (image.length % BLOCK) throw new SyxError(`image length ${image.length} is not a multiple of ${BLOCK}`);
  const n = image.length / BLOCK;
  const msgLen = SEPTETS + 7;
  const out = new Uint8Array(header.length + 7 + n * msgLen);
  out.set(frame(CMD_HEADER, header), 0);
  let pos = header.length + 7;
  for (let off = BLOCK; off < image.length; off += BLOCK) {
    out.set(frame(CMD_DATA, pack(image.subarray(off, off + BLOCK))), pos);
    pos += msgLen;
  }
  out.set(frame(CMD_FINAL, pack(image.subarray(0, BLOCK))), pos);
  return out;
}

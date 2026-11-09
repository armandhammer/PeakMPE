// The Components firmware update protocol, a port of tools/flash.py
// (docs/update-protocol.md). Transport-independent: the page passes a Web MIDI
// backend, the tests a fake bootloader (fake.ts).
//
//   1. identify the application (Universal Device Inquiry), check the product;
//   2. send the file's own 0x71 header to the application port: it reboots and
//      "Summit Bootloader" ports appear (<= 12 s), then wait 100 ms;
//   3. identify the bootloader, then send the file's messages in order, one per
//      device 0x72 request; the counter is the number of messages received
//      (1, 2, ...); repeated requests are ignored (t > last || t == 0);
//      10 s per request (the first block is followed by a ~3.4 s erase pause);
//   4. after the final 0x73 block, wait for the application port and retry the
//      identity request until it answers (~2-6 s after 0x73 on hardware).

import { CMD_DATA, CMD_FINAL, CMD_HEADER, SEPTETS } from "../core/syx";

export const IDENTITY_REQUEST = Uint8Array.from([0xf0, 0x7e, 0x7f, 0x06, 0x01, 0xf7]);
const NOVATION = [0xf0, 0x00, 0x20, 0x29, 0x00];
const PRODUCTS: Record<string, string> = { "1,51": "Summit", "0,126": "Peak" };

const identityTemplate = (dev: number, family: [number, number]) =>
  [0x7e, dev, 0x06, 0x02, 0x00, 0x20, 0x29, ...family, 0x00, 0x00];
export const IDENTITY_TEMPLATES: Record<string, number[][]> = {
  Summit: [identityTemplate(0x7f, [0x33, 0x01]), identityTemplate(0x00, [0x33, 0x11])],
  Peak: [identityTemplate(0x7f, [0x7e, 0x00]), identityTemplate(0x00, [0x7e, 0x10])],
};

// FPGA version query to the application (docs/update-protocol.md §1, sent by
// Components on every connect). Reply bytes 1-8 = 00 20 29 00 7C <pid> 40,
// version in bytes 11-14, one digit per byte, least significant first.
const PRODUCT_ID: Record<string, [number, number]> = { Summit: [0x01, 0x33], Peak: [0x00, 0x7e] };
export const fpgaRequest = (product: string) =>
  Uint8Array.from([...NOVATION, 0x7c, ...PRODUCT_ID[product], 0x44, 0, 0, 0, 0, 0, 0, 0xf7]);
/** The FPGA build that goes with firmware 2.2 (FPGA 2.1, build 778). */
export const EXPECTED_FPGA: Record<string, number> = { Summit: 778 };

export function parseFpga(msg: Uint8Array, product: string): number | null {
  if (msg.length < 16 || !startsWith(msg, [...NOVATION, 0x7c, ...PRODUCT_ID[product], 0x40])) return null;
  return msg[11] + msg[12] * 10 + msg[13] * 100 + msg[14] * 1000;
}

export const TIMING = {
  waitForBootloader: 12000, // Summit maxWaitForResetTimeout
  settleAfterBootloader: 100,
  requestTimeout: 10000, // FIRMWARE_UPDATE_TIMEOUT
  waitForApplication: 30000,
  identityTimeout: 2000,
  poll: 200,
};
export type Timing = typeof TIMING;

/**
 * "no-identity": the synth didn't answer the identity request before anything
 * was sent that changes it. Seen on hardware (2026-11-08, Vivaldi 8.3 on
 * macOS): the browser sent the request and the Summit answered (CoreMIDI
 * delivered the reply to other apps), but the browser's Web MIDI input
 * passed nothing on; after a browser restart it worked.
 */
export type FlashErrorCode = "no-identity";

export class FlashError extends Error {
  constructor(message: string, readonly code?: FlashErrorCode) {
    super(message);
  }
}

const startsWith = (msg: Uint8Array, prefix: number[]) => prefix.every((b, i) => msg[i] === b);

// ------------------------------------------------------------------ the file

export class Plan {
  readonly messages: Uint8Array[] = [];
  readonly product: string;
  readonly version: string;

  /** Validate a firmware file before any MIDI is opened (flash.py's Plan). */
  constructor(readonly data: Uint8Array) {
    let pos = 0;
    while (pos < data.length) {
      if (data[pos] !== 0xf0) throw new FlashError(`expected F0 at offset 0x${pos.toString(16)}`);
      const end = data.indexOf(0xf7, pos);
      if (end < 0) throw new FlashError("unterminated SysEx message");
      this.messages.push(data.subarray(pos, end + 1));
      pos = end + 1;
    }
    const cmds = this.messages.map((m) => (startsWith(m, NOVATION) ? m[5] : -1));
    if (cmds.includes(-1)) throw new FlashError("file contains non-Novation SysEx");
    if (cmds.includes(0x7c)) throw new FlashError("this is an FPGA image (0x7C); only firmware files are supported");
    const middle = new Set(cmds.slice(1, -1));
    if (cmds.length < 3 || cmds[0] !== CMD_HEADER || cmds[cmds.length - 1] !== CMD_FINAL ||
        middle.size !== 1 || !middle.has(CMD_DATA))
      throw new FlashError("expected one 0x71 header, then 0x72 blocks, then one 0x73 final block");
    if (this.messages.slice(1).some((m) => m.length !== 6 + SEPTETS + 1))
      throw new FlashError("a data block has the wrong length");
    const header = this.messages[0].subarray(6, -1);
    const product = PRODUCTS[`${header[0]},${header[1]}`];
    if (!product) throw new FlashError("unknown product id in the file header");
    this.product = product;
    this.version = Array.from(header.subarray(4, 8)).join("");
  }
}

// ------------------------------------------------------------ device replies

export function parseIdentity(msg: Uint8Array): { product: string; version: string } | null {
  if (msg.length < 17 || msg[0] !== 0xf0) return null;
  for (const [product, templates] of Object.entries(IDENTITY_TEMPLATES)) {
    if (templates.some((t) => t.every((b, i) => msg[i + 1] === b)))
      return { product, version: Array.from(msg.subarray(12, 16)).join("") };
  }
  return null;
}

/** Device 0x72 "send next" request -> counter, else null. */
export function parseRequest(msg: Uint8Array): number | null {
  if (!startsWith(msg, [...NOVATION, 0x72])) return null;
  if (msg.length === 10) return msg[6] + (msg[7] << 7) + (msg[8] << 14);
  if (msg.length === 15) {
    const e = msg.subarray(6, 14);
    return e[7] + (e[6] << 4) + (e[5] << 8);
  }
  return null;
}

export function parseStatus(msg: Uint8Array): number | null {
  return msg.length === 10 && startsWith(msg, [...NOVATION, 0x73]) ? msg[6] : null;
}

const STATUS_FATAL: Record<number, string> = {
  0x7c: "the device reported a CRC error (composition not viable)",
  0x7e: "the device reported a CRC error (composition viable)",
  0x10: "the update was cancelled on the device",
};

/** Stop-and-wait sender for the bootloader stream (s1.#$i in Components). */
export class Transfer {
  index = 0;
  lastCounter = 0;
  done = false;

  constructor(private readonly messages: Uint8Array[]) {}

  start(): Uint8Array {
    this.index = 1;
    return this.messages[0];
  }

  /** The next message to send, or null to keep waiting. */
  onMessage(msg: Uint8Array): Uint8Array | null {
    const status = parseStatus(msg);
    if (status !== null && status in STATUS_FATAL) throw new FlashError(`${STATUS_FATAL[status]} at block ${this.index}`);
    if (status === 0x7f) return this.next();
    const counter = parseRequest(msg);
    if (counter === null) return null;
    if (counter > this.lastCounter || counter === 0) {
      this.lastCounter = counter;
      return this.next();
    }
    return null;
  }

  private next(): Uint8Array | null {
    if (this.done || this.index >= this.messages.length) return null;
    const msg = this.messages[this.index++];
    this.done = this.index === this.messages.length;
    return msg;
  }
}

// ----------------------------------------------------------------- transport

export interface MidiPort {
  readonly name: string;
  send(msg: Uint8Array): void;
  /** The next message received, or null after timeoutMs. */
  receive(timeoutMs: number): Promise<Uint8Array | null>;
  close(): Promise<void>;
}

export interface MidiBackend {
  /** Names of ports that exist as both an input and an output. */
  portNames(): string[];
  open(name: string): Promise<MidiPort>;
}

export function findPort(backend: MidiBackend, product: string, bootloader: boolean): string | null {
  const names = backend.portNames().filter((n) => n.includes(product) && n.includes("Bootloader") === bootloader);
  if (names.length > 1) throw new FlashError(`several matching MIDI ports: ${names.join(", ")}; disconnect the others`);
  return names[0] ?? null;
}

export async function identify(port: MidiPort, timeoutMs: number) {
  port.send(IDENTITY_REQUEST);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const msg = await port.receive(Math.max(0, deadline - Date.now()));
    if (!msg) break;
    const ident = parseIdentity(msg);
    if (ident) return ident;
  }
  return null;
}

/** The FPGA build the application reports, or null if it doesn't answer. */
export async function queryFpga(port: MidiPort, product: string, timeoutMs: number): Promise<number | null> {
  port.send(fpgaRequest(product));
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const msg = await port.receive(Math.max(0, deadline - Date.now()));
    if (!msg) break;
    const v = parseFpga(msg, product);
    if (v !== null) return v;
  }
  return null;
}

// ------------------------------------------------------------------ the flow

export type Phase = "identify" | "reboot" | "transfer" | "restart" | "done";

export interface FlashEvents {
  log?(text: string): void;
  phase?(p: Phase): void;
  progress?(sent: number, total: number): void;
  /** Asked once the device is known; resolve false to stop before anything is written. */
  confirm(question: string): Promise<boolean>;
  /** Raw traffic, for a downloadable log. */
  midi?(direction: ">" | "<", port: string, msg: Uint8Array): void;
}

export interface FlashResult {
  /** The version the application reported after the reboot, or null if it did not answer. */
  version: string | null;
  matchesFile: boolean;
  messagesSent: number;
  /** The FPGA build the restarted synth reports, or null if unknown. */
  fpga: number | null;
  /** True when the FPGA is older than the one that goes with this firmware (update it with Components). */
  fpgaBehind: boolean;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function logged(port: MidiPort, ev: FlashEvents): MidiPort {
  return {
    name: port.name,
    send(msg) {
      ev.midi?.(">", port.name, msg);
      port.send(msg);
    },
    async receive(t) {
      const msg = await port.receive(t);
      if (msg) ev.midi?.("<", port.name, msg);
      return msg;
    },
    close: () => port.close(),
  };
}

async function waitForPort(backend: MidiBackend, product: string, bootloader: boolean, ms: number, t: Timing) {
  const deadline = Date.now() + ms;
  for (;;) {
    const name = findPort(backend, product, bootloader);
    if (name || Date.now() >= deadline) return name;
    await sleep(t.poll);
  }
}

/** Run the whole update, as flash.py's flash(). Throws FlashError on any failure. */
export async function flash(plan: Plan, backend: MidiBackend, ev: FlashEvents, t: Timing = TIMING): Promise<FlashResult> {
  const say = (s: string) => ev.log?.(s);
  const product = plan.product;
  const total = plan.messages.length;
  say(`${product} firmware ${plan.version}, ${total} messages`);
  ev.phase?.("identify");

  let bootName = findPort(backend, product, true);
  if (bootName) {
    say(`bootloader already active on "${bootName}" (manual entry / recovery path)`);
    if (!(await ev.confirm(`Send this ${product} firmware to "${bootName}"?`))) throw new FlashError("not confirmed");
  } else {
    const mainName = findPort(backend, product, false);
    if (!mainName) throw new FlashError(`no "${product}" MIDI port found; is the synth connected over USB?`);
    const main = logged(await backend.open(mainName), ev);
    try {
      const ident = await identify(main, t.identityTimeout);
      if (!ident) throw new FlashError(`no identity reply on "${mainName}"`, "no-identity");
      if (ident.product !== product) throw new FlashError(`the device is a ${ident.product} but the file is ${product} firmware`);
      say(`device: ${ident.product} on "${mainName}", firmware ${ident.version}`);
      const fpga = await queryFpga(main, product, t.identityTimeout);
      say(`FPGA: ${fpga ?? "no answer"}` + (fpga !== null && fpga < EXPECTED_FPGA[product]
        ? ` (older than ${EXPECTED_FPGA[product]}: update it with Novation Components afterwards)` : ""));
      if (!(await ev.confirm(`Reboot the ${product} into its bootloader and flash this file?`)))
        throw new FlashError("not confirmed");
      ev.phase?.("reboot");
      main.send(plan.messages[0]);
    } finally {
      await main.close();
    }
    say("waiting for the bootloader ports ...");
    bootName = await waitForPort(backend, product, true, t.waitForBootloader, t);
    if (!bootName) throw new FlashError(`the bootloader ports did not appear within ${t.waitForBootloader / 1000} s`);
    await sleep(t.settleAfterBootloader);
  }

  ev.phase?.("transfer");
  const boot = logged(await backend.open(bootName), ev);
  const transfer = new Transfer(plan.messages);
  try {
    const ident = await identify(boot, t.identityTimeout);
    if (!ident) throw new FlashError(`no identity reply from "${bootName}"`);
    if (ident.product !== product) throw new FlashError(`the bootloader is a ${ident.product} but the file is ${product} firmware`);
    say(`bootloader: ${ident.product} on "${bootName}", reports ${ident.version}`);
    boot.send(transfer.start());
    ev.progress?.(transfer.index, total);
    while (!transfer.done) {
      const msg = await boot.receive(t.requestTimeout);
      if (!msg)
        throw new FlashError(`no request from the device for ${t.requestTimeout / 1000} s after message ` +
          `${transfer.index - 1} of ${total} (last counter ${transfer.lastCounter}). ` +
          "Restart the update from the beginning in bootloader mode (see Recovery).");
      const next = transfer.onMessage(msg);
      if (next) {
        boot.send(next);
        ev.progress?.(transfer.index, total);
      }
    }
  } finally {
    await boot.close();
  }

  ev.phase?.("restart");
  say("transfer complete; waiting for the synth to restart ...");
  let mainName = await waitForPort(backend, product, false, t.waitForApplication, t);
  if (!mainName) {
    say("Unable to confirm the update: the application ports did not return");
    return { version: null, matchesFile: false, messagesSent: transfer.index, fpga: null, fpgaBehind: false };
  }
  // The port is back ~2 s after the final block; the application may answer only ~6 s after it.
  let ident = null;
  let fpga: number | null = null;
  const attempts = Math.ceil(t.waitForApplication / t.identityTimeout);
  for (let i = 0; i < attempts && !ident; i++) {
    mainName = findPort(backend, product, false);
    if (mainName) {
      const main = logged(await backend.open(mainName), ev);
      try {
        ident = await identify(main, t.identityTimeout);
        if (ident) fpga = await queryFpga(main, product, t.identityTimeout);
      } finally {
        await main.close();
      }
    }
    if (!ident) await sleep(t.poll);
  }
  ev.phase?.("done");
  if (!ident) {
    say("Unable to confirm the update: no identity reply after the reboot");
    return { version: null, matchesFile: false, messagesSent: transfer.index, fpga: null, fpgaBehind: false };
  }
  const matchesFile = ident.version === plan.version;
  const fpgaBehind = fpga !== null && fpga < EXPECTED_FPGA[product];
  say(`synth back: ${ident.product} firmware ${ident.version}` +
    (matchesFile ? ", as in the file header" : `, but the file header says ${plan.version}`) +
    `; FPGA ${fpga ?? "unknown"}`);
  return { version: ident.version, matchesFile, messagesSent: transfer.index, fpga, fpgaBehind };
}

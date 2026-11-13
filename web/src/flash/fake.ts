// A simulated Summit or Peak (`product`) for the tests and the page's practice mode. It follows
// tools/flash.py's SimulatedSynth and the hardware captures in
// docs/update-protocol.md:
//
//   - the application answers the identity request; a 0x71 header reboots it;
//     the "Summit Bootloader" port appears after bootDelayMs;
//   - the bootloader answers identity with its own template, then after each
//     message sends one 0x72 request whose counter is the number of messages
//     received so far (1, 2, ...); after the first data block it pauses
//     eraseMs (the flash erase, 3.4 s on hardware);
//   - every repeatEvery-th request is sent twice (hardware: every ~35-45);
//   - nothing comes back after the final 0x73; the application port returns
//     after appDelayMs and ignores its first slowBoot identity requests.
//
// Faults: stallAfter (stop requesting after N messages), statusAfter
// ([N, code]: a 0x73 status report instead of request N), keepVersion, deaf
// (the synth answers, but nothing reaches the page: a browser whose Web MIDI
// input stopped passing messages on).

import { CMD_FINAL, CMD_HEADER } from "../core/syx";
import { fpgaRequest, IDENTITY_REQUEST, IDENTITY_TEMPLATES, type MidiBackend, type MidiPort } from "./protocol";

export interface FakeOptions {
  product?: string;
  version?: string;
  startInBootloader?: boolean;
  bootDelayMs?: number;
  eraseMs?: number;
  requestDelayMs?: number;
  repeatEvery?: number;
  appDelayMs?: number;
  slowBoot?: number;
  stallAfter?: number;
  statusAfter?: [number, number];
  keepVersion?: boolean;
  deaf?: boolean;
  /** FPGA build the application reports (default 778); null: no answer. */
  fpga?: number | null;
}

const NOVATION = [0xf0, 0x00, 0x20, 0x29, 0x00];

export class FakeSummit implements MidiBackend {
  mode: "app" | "boot" | "off";
  version: string;
  readonly received: Uint8Array[] = [];
  readonly opts: Required<Omit<FakeOptions, "stallAfter" | "statusAfter" | "fpga" | "deaf">> & FakeOptions;
  private inbox: Uint8Array[] = [];
  private waiter: ((m: Uint8Array | null) => void) | null = null;
  private ignoreIdentity = 0;
  identityRequests = 0;

  constructor(opts: FakeOptions = {}) {
    this.opts = {
      product: "Summit", version: "2126", startInBootloader: false, bootDelayMs: 0, eraseMs: 0,
      requestDelayMs: 0, repeatEvery: 0, appDelayMs: 0, slowBoot: 0, keepVersion: false, ...opts,
    };
    this.version = this.opts.version;
    this.mode = this.opts.startInBootloader ? "boot" : "app";
  }

  portNames(): string[] {
    if (this.mode === "off") return [];
    return [this.mode === "boot" ? `${this.opts.product} Bootloader` : this.opts.product];
  }

  async open(name: string): Promise<MidiPort> {
    if (!this.portNames().includes(name)) throw new Error(`no such port ${name}`);
    this.inbox = [];
    return {
      name,
      send: (msg) => this.handle(Uint8Array.from(msg)),
      receive: (timeoutMs) => this.receive(timeoutMs),
      close: async () => {
        this.waiter?.(null);
        this.waiter = null;
      },
    };
  }

  private receive(timeoutMs: number): Promise<Uint8Array | null> {
    const m = this.inbox.shift();
    if (m) return Promise.resolve(m);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.waiter = null;
        resolve(null);
      }, timeoutMs);
      this.waiter = (msg) => {
        clearTimeout(timer);
        this.waiter = null;
        resolve(msg);
      };
    });
  }

  private reply(msg: Uint8Array, delayMs = 0) {
    if (this.opts.deaf) return;
    const deliver = () => {
      if (this.waiter) this.waiter(msg);
      else this.inbox.push(msg);
    };
    if (delayMs > 0) setTimeout(deliver, delayMs);
    else queueMicrotask(deliver);
  }

  private identity(): Uint8Array {
    const t = IDENTITY_TEMPLATES[this.opts.product][this.mode === "boot" ? 1 : 0];
    return Uint8Array.from([0xf0, ...t, ...Array.from(this.version, Number), 0xf7]);
  }

  private handle(msg: Uint8Array) {
    if (msg.length === IDENTITY_REQUEST.length && msg.every((b, i) => b === IDENTITY_REQUEST[i])) {
      this.identityRequests++;
      if (this.ignoreIdentity > 0) {
        this.ignoreIdentity--;
        return;
      }
      this.reply(this.identity());
      return;
    }
    if (this.mode === "app") {
      const q = fpgaRequest(this.opts.product);
      if (msg.length === q.length && msg.every((b, i) => b === q[i])) {
        const v = this.opts.fpga === undefined ? (this.opts.product === "Peak" ? 469 : 778) : this.opts.fpga;
        if (v !== null) {
          const pid = q.subarray(6, 8);
          this.reply(Uint8Array.from([...NOVATION, 0x7c, ...pid, 0x40, 0x45, 0x12,
            v % 10, Math.floor(v / 10) % 10, Math.floor(v / 100) % 10, Math.floor(v / 1000) % 10, 0xf7]));
        }
        return;
      }
      if (NOVATION.every((b, i) => msg[i] === b) && msg[5] === CMD_HEADER) {
        this.mode = "off";
        setTimeout(() => (this.mode = "boot"), this.opts.bootDelayMs);
      }
      return;
    }
    if (this.mode !== "boot") return;
    this.received.push(msg);
    const n = this.received.length;
    if (msg[5] === CMD_FINAL) {
      this.mode = "off";
      if (!this.opts.keepVersion) this.version = Array.from(this.received[0].subarray(10, 14)).join("");
      setTimeout(() => {
        this.mode = "app";
        this.ignoreIdentity = this.opts.slowBoot;
      }, this.opts.appDelayMs);
      return;
    }
    if (this.opts.statusAfter && n === this.opts.statusAfter[0]) {
      this.reply(Uint8Array.from([...NOVATION, 0x73, this.opts.statusAfter[1], 0, 0, 0xf7]));
      return;
    }
    if (this.opts.stallAfter !== undefined && n >= this.opts.stallAfter) return;
    const req = Uint8Array.from([...NOVATION, 0x72, n & 0x7f, (n >> 7) & 0x7f, (n >> 14) & 0x7f, 0xf7]);
    const delay = n === 2 ? this.opts.eraseMs : this.opts.requestDelayMs;
    this.reply(req, delay);
    if (this.opts.repeatEvery && n % this.opts.repeatEvery === 0) this.reply(req, delay);
  }
}

import { describe, expect, it } from "vitest";
import { FakeSummit } from "../src/flash/fake";
import { flash, FlashError, Plan, TIMING, Transfer, type Timing } from "../src/flash/protocol";
import { encode } from "../src/core/syx";
import { fakeImage, HEADER } from "./fixtures";

const fast: Timing = { ...TIMING, waitForBootloader: 500, settleAfterBootloader: 1, requestTimeout: 300,
  waitForApplication: 600, identityTimeout: 40, poll: 5 };
const yes = { confirm: async () => true };
const file = (header = HEADER) => encode(header, fakeImage(60));
const concat = (parts: Uint8Array[]) => Buffer.concat(parts.map((p) => Buffer.from(p)));

describe("Plan", () => {
  it("accepts a firmware file and reads product and version", () => {
    const p = new Plan(file());
    expect(p.product).toBe("Summit");
    expect(p.version).toBe("2126");
    expect(p.messages.length).toBe(61);
  });
  it("refuses FPGA, foreign and malformed files", () => {
    expect(() => new Plan(Uint8Array.from([0xf0, 0, 0x20, 0x29, 0, 0x7c, 1, 0xf7]))).toThrow(/FPGA/);
    expect(() => new Plan(Uint8Array.from([0xf0, 0x43, 0, 0xf7]))).toThrow(FlashError);
    const f = file();
    expect(() => new Plan(f.subarray(0, f.length - 44))).toThrow(/final block/);
    expect(() => new Plan(file(Uint8Array.from([9, 9, 0, 0, 2, 1, 2, 6])))).toThrow(/unknown product/);
  });
});

describe("Transfer gate", () => {
  it("sends one message per new counter and ignores repeats", () => {
    const msgs = [1, 2, 3, 4].map((i) => Uint8Array.of(i));
    const t = new Transfer(msgs);
    const req = (n: number) => Uint8Array.from([0xf0, 0, 0x20, 0x29, 0, 0x72, n, 0, 0, 0xf7]);
    expect(t.start()).toEqual(Uint8Array.of(1));
    expect(t.onMessage(req(1))).toEqual(Uint8Array.of(2));
    expect(t.onMessage(req(1))).toBeNull();
    expect(t.onMessage(req(2))).toEqual(Uint8Array.of(3));
    expect(t.onMessage(req(0))).toEqual(Uint8Array.of(4)); // t == 0 passes, as in Components
    expect(t.done).toBe(true);
  });
});

describe("flash against the fake bootloader", () => {
  it("reboots, sends every message exactly once in order, and sees the new version", async () => {
    const data = file(Uint8Array.from([1, 0x33, 0, 0, 2, 1, 2, 7]));
    const synth = new FakeSummit({ bootDelayMs: 30, eraseMs: 60, repeatEvery: 7, appDelayMs: 50, slowBoot: 2 });
    const phases: string[] = [];
    const r = await flash(new Plan(data), synth, { ...yes, phase: (p) => phases.push(p) }, fast);
    expect(concat(synth.received).equals(Buffer.from(data))).toBe(true);
    expect(r).toEqual({ version: "2127", matchesFile: true, messagesSent: 61, fpga: 778, fpgaBehind: false });
    expect(phases).toEqual(["identify", "reboot", "transfer", "restart", "done"]);
    expect(synth.identityRequests).toBeGreaterThanOrEqual(5); // app, bootloader, 2 ignored, answered
  });

  it("uses the recovery path when the bootloader is already active", async () => {
    const data = file();
    const synth = new FakeSummit({ startInBootloader: true, version: "2127" });
    const questions: string[] = [];
    const r = await flash(new Plan(data), synth, { confirm: async (q) => (questions.push(q), true) }, fast);
    expect(questions[0]).toMatch(/Summit Bootloader/);
    expect(concat(synth.received).equals(Buffer.from(data))).toBe(true);
    expect(r.version).toBe("2126");
  });

  it("sends nothing when the user declines", async () => {
    const synth = new FakeSummit();
    await expect(flash(new Plan(file()), synth, { confirm: async () => false }, fast)).rejects.toThrow(/not confirmed/);
    expect(synth.mode).toBe("app");
    expect(synth.received.length).toBe(0);
  });

  it("refuses a Peak", async () => {
    const synth = new FakeSummit({ product: "Peak" });
    synth.portNames = () => ["Summit"]; // a Peak behind a port named like a Summit
    await expect(flash(new Plan(file()), synth, yes, fast)).rejects.toThrow(/is a Peak/);
    expect(synth.received.length).toBe(0);
  });

  it("stops on a stall and says to restart from the beginning", async () => {
    const synth = new FakeSummit({ stallAfter: 20 });
    await expect(flash(new Plan(file()), synth, yes, fast)).rejects.toThrow(/last counter 19.*Restart the update/);
    expect(synth.received.at(-1)![5]).toBe(0x72); // the vector block was never sent
  });

  it("aborts on a CRC status report", async () => {
    const synth = new FakeSummit({ statusAfter: [10, 0x7c] });
    await expect(flash(new Plan(file()), synth, yes, fast)).rejects.toThrow(/CRC error/);
  });

  it("reports when the synth does not come back, without calling it a failure", async () => {
    const synth = new FakeSummit({ slowBoot: 1000 });
    const r = await flash(new Plan(file()), synth, yes, fast);
    expect(r.version).toBeNull();
    expect(r.messagesSent).toBe(61);
  });

  it("says when the synth reports another version than the file", async () => {
    const synth = new FakeSummit({ keepVersion: true, version: "2125" });
    const r = await flash(new Plan(file()), synth, yes, fast);
    expect(r).toMatchObject({ version: "2125", matchesFile: false });
  });

  it("reports an FPGA older than 778, and an unknown one", async () => {
    let r = await flash(new Plan(file()), new FakeSummit({ fpga: 469 }), yes, fast);
    expect(r).toMatchObject({ version: "2126", fpga: 469, fpgaBehind: true });
    r = await flash(new Plan(file()), new FakeSummit({ fpga: null }), yes, fast);
    expect(r).toMatchObject({ version: "2126", fpga: null, fpgaBehind: false });
  });

  it("says when the synth's answers don't reach the page, before anything is sent", async () => {
    const synth = new FakeSummit({ deaf: true });
    const err = await flash(new Plan(file()), synth, yes, fast).catch((e) => e);
    expect(err).toBeInstanceOf(FlashError);
    expect(err.code).toBe("no-identity");
    expect(err.message).toMatch(/no identity reply on "Summit"/);
    expect(synth.identityRequests).toBe(1);
    expect(synth.mode).toBe("app");
    expect(synth.received.length).toBe(0);
  });

  it("fails when there is no synth", async () => {
    const synth = new FakeSummit();
    synth.mode = "off";
    await expect(flash(new Plan(file()), synth, yes, fast)).rejects.toThrow(/no "Summit" MIDI port/);
  });
});

describe("FPGA reply", () => {
  it("parses the captured Components reply as 778", async () => {
    const { parseFpga } = await import("../src/flash/protocol");
    const reply = Uint8Array.from([0xf0, 0, 0x20, 0x29, 0, 0x7c, 0x01, 0x33, 0x40, 0x45, 0x12, 0x08, 0x07, 0x07, 0x00, 0xf7]);
    expect(parseFpga(reply, "Summit")).toBe(778);
    expect(parseFpga(reply, "Peak")).toBeNull();
  });
});

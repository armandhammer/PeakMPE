import { describe, expect, it } from "vitest";
import { contentFor } from "../src/content";
import { parseDescriptor } from "../src/core/descriptor";
import { otherProduct, pickProduct, PRODUCTS } from "../src/product";

const allStrings = (o: unknown): string[] =>
  typeof o === "string" ? [o] : Object.values(o as object).flatMap(allStrings);

describe("products", () => {
  it("picks the synth from ?synth=, the Summit by default", () => {
    expect(pickProduct("").id).toBe("summit");
    expect(pickProduct("?synth=peak").id).toBe("peak");
    expect(pickProduct("?synth=PEAK").id).toBe("peak");
    expect(pickProduct("?synth=other").id).toBe("summit");
  });

  it("each descriptor is for its own synth's official file", () => {
    const s = parseDescriptor(PRODUCTS.summit.descriptor);
    const p = parseDescriptor(PRODUCTS.peak.descriptor);
    expect(s.input.fileName).toBe("summit-firmware-2.2-build2121.syx");
    expect(p.input.fileName).toBe("peak-firmware-2.2-build2108.syx");
    expect(p.input.sha256).toBe("f9d50b4268a5c612b71d4cafd45dc01a02ecdf0902aa6e31784ad4d1bc4de26e");
    // MPE for Peak 0.1 with the per-zone master bend (2026-11-12); the image before
    // that fix, c961f3a1..., is the one first flashed and tested (docs/hardware-log.md)
    expect(p.output.sha256).toBe("bc3bf703f94c2791e666edff503a09bd42c30863988ce6dc6fd20c3a2c99532a");
    expect(p.title).toBe("MPE for Peak");
  });

  it("the Peak page names only the Peak, and keeps no Multis", () => {
    const c = contentFor(PRODUCTS.peak, otherProduct(PRODUCTS.peak));
    const text = allStrings(c).join("\n");
    expect(text).not.toMatch(/\{(synth|build|backupWhat|backupShort|other|otherId)\}/);
    expect(text.replace(/the Summit version of this page|For the Summit/g, "")).not.toContain("Summit");
    expect(text).not.toContain("Multis");
    expect(c.steps.file.official).toBe("Official Peak firmware 2.2 (build 2108), checksum verified.");
    expect(c.otherSynth).toContain("?synth=summit");
  });

  it("the Summit page reads as before", () => {
    const c = contentFor(PRODUCTS.summit, otherProduct(PRODUCTS.summit));
    expect(c.title).toBe("Summit MPE firmware patcher");
    expect(c.steps.file.official).toBe("Official Summit firmware 2.2 (build 2121), checksum verified.");
    expect(c.backup.checkbox).toContain("all my patches and Multis");
    expect(c.otherSynth).toContain("?synth=peak");
  });
});

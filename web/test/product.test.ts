import { describe, expect, it } from "vitest";
import { contentFor } from "../src/content";
import { parseDescriptor } from "../src/core/descriptor";
import { PAGE_PRODUCT, PRODUCTS } from "../src/product";

const allStrings = (o: unknown): string[] =>
  typeof o === "string" ? [o] : Object.values(o as object).flatMap(allStrings);

describe("products", () => {
  it("the page is for the Peak", () => {
    expect(PAGE_PRODUCT.id).toBe("peak");
  });

  it("each descriptor is for its own synth's official file", () => {
    const s = parseDescriptor(PRODUCTS.summit.descriptor);
    const p = parseDescriptor(PRODUCTS.peak.descriptor);
    expect(s.input.fileName).toBe("summit-firmware-2.2-build2121.syx");
    expect(p.input.fileName).toBe("peak-firmware-2.2-build2108.syx");
    expect(p.input.sha256).toBe("f9d50b4268a5c612b71d4cafd45dc01a02ecdf0902aa6e31784ad4d1bc4de26e");
    // MPE for Peak 0.1 with the per-zone master bend, flashed and tested on a Peak
    // 2026-11-13 (docs/hardware-log.md)
    expect(p.output.sha256).toBe("bc3bf703f94c2791e666edff503a09bd42c30863988ce6dc6fd20c3a2c99532a");
    expect(p.title).toBe("MPE for Peak");
  });

  it("the Peak page names only the Peak, and keeps no Multis", () => {
    const c = contentFor(PRODUCTS.peak);
    const text = allStrings(c).join("\n");
    expect(text).not.toMatch(/\{(synth|build|backupWhat|backupShort)\}/);
    expect(text).not.toContain("Summit");
    expect(text).not.toContain("Multis");
    expect(c.title).toBe("Peak MPE firmware patcher");
    expect(c.steps.file.official).toBe("Official Peak firmware 2.2 (build 2108), checksum verified.");
  });

  it("the Summit text still fills in (upstream's wording)", () => {
    const c = contentFor(PRODUCTS.summit);
    expect(c.steps.file.official).toBe("Official Summit firmware 2.2 (build 2121), checksum verified.");
    expect(c.backup.checkbox).toContain("all my patches and Multis");
  });
});

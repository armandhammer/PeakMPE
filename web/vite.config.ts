import tailwindcss from "@tailwindcss/vite";
import { realpathSync } from "node:fs";
import { defineConfig } from "vitest/config";

// SUMMIT_DEV_FIRMWARE_DIR (dev server only): also serve that folder under
// /@fs/, so a local browser test can fetch the official file. Never used by
// `vite build`; the site never ships or fetches firmware.
const devFirmware = process.env.SUMMIT_DEV_FIRMWARE_DIR;

// base "./": the build works from any path, e.g. https://<user>.github.io/<repo>/.
export default defineConfig({
  base: "./",
  plugins: [tailwindcss()],
  server: devFirmware ? { fs: { allow: [".", realpathSync(devFirmware)] } } : {},
  test: {
    include: ["test/**/*.test.ts"],
    testTimeout: 20000,
  },
});

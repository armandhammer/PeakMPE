// The synths this repository has patch descriptors for. The page itself is
// for the Peak only (PAGE_PRODUCT).

import summitDescriptor from "../patches/mpe.json";
import peakDescriptor from "../patches/peak-mpe.json";

export interface Product {
  id: "summit" | "peak";
  /** As the synth names itself on USB and in its identity reply. */
  name: string;
  /** Official firmware build the patch applies to. */
  build: string;
  /** The version the stock application reports (Summit 2121's application says 2126). */
  stockVersion: string;
  /** Novation's download (Components catalogue), and the name the file arrives with. */
  officialFirmware: string;
  officialFirmwareName: string;
  /** FPGA build that goes with firmware 2.2. */
  expectedFpga: number;
  /** What a backup with Novation Components covers on this synth. */
  backupWhat: string;
  backupShort: string;
  descriptor: unknown;
}

export const PRODUCTS: Record<Product["id"], Product> = {
  summit: {
    id: "summit",
    name: "Summit",
    build: "2121",
    stockVersion: "2126",
    officialFirmware: "https://components.novationmusic.com/api/v2/firmwares/154/file",
    officialFirmwareName: "summit-firmware-2121.syx",
    expectedFpga: 778,
    backupWhat: "patches (sounds) and Multis",
    backupShort: "patches and Multis",
    descriptor: summitDescriptor,
  },
  peak: {
    id: "peak",
    name: "Peak",
    build: "2108",
    stockVersion: "2108",
    // Catalogue id 155 (scripts/fetch-firmware.sh). The download's file name
    // is inferred from the Summit's pattern; the page checks the hash, not the name.
    officialFirmware: "https://components.novationmusic.com/api/v2/firmwares/155/file",
    officialFirmwareName: "peak-firmware-2108.syx",
    expectedFpga: 469,
    backupWhat: "patches (sounds)",
    backupShort: "patches",
    descriptor: peakDescriptor,
  },
};

/** The page is for the Peak (this repository's port). The Summit's entry
 * stays for the descriptor and parity tests; upstream's page serves it. */
export const PAGE_PRODUCT: Product = PRODUCTS.peak;

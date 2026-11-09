// All text on the page. Edit here; main.ts only places it.
// Strings marked (html) may contain simple markup; everything else is plain text.
// {placeholders} are filled in by main.ts from the patch descriptor.

export const links = {
  officialFirmware: "https://components.novationmusic.com/api/v2/firmwares/154/file",
  officialFirmwareName: "summit-firmware-2121.syx",
  // Set at build time: the release workflow passes VITE_SOURCE_URL from
  // GITHUB_SERVER_URL/GITHUB_REPOSITORY, so a fork's page links to the fork.
  // Empty in a local build; the footer then names no URL.
  source: (import.meta.env.VITE_SOURCE_URL as string | undefined) ?? "",
  components: "https://components.novationmusic.com/",
};

export const content = {
  title: "Summit MPE firmware patcher",
  subtitle: "An unofficial, community-made MPE mod for the Summit synthesizer, applied in your browser.",

  // (html) Always visible at the top.
  banner:
    "<strong>Unofficial and vibe-coded.</strong> This project and its firmware patch were built with an AI " +
    "coding assistant. It is not affiliated with, endorsed by or supported by Novation or Focusrite. " +
    "“Novation”, “Focusrite” and “Summit” are their trademarks and are used here only to say which instrument this is for.",

  about: {
    heading: "What this does",
    // (html)
    body:
      "<p>{summary}</p>" +
      "<p>After flashing, the boot screen shows <code>{label}</code>. Switch MPE on per sound on the VOICE page, " +
      "and set the zone on the Settings MPE page.</p>" +
      "<p>The site never hosts Novation's firmware. You download it from Novation yourself; this page checks " +
      "it, applies the patch on your computer (nothing is uploaded) and checks the result against the " +
      "expected checksum before it lets you download or flash it.</p>",
  },

  disclaimer: {
    heading: "Read this first",
    // (html)
    body:
      "<p>This software and the modified firmware are provided <strong>“as is”, without warranty of any kind</strong>, " +
      "express or implied, including fitness for a particular purpose. They were built by hobbyists with an AI " +
      "coding assistant and have been tested on one instrument only.</p>" +
      "<p>Flashing modified firmware may void your warranty, may cause the instrument to malfunction, and may " +
      "make it unusable or damage it permanently. <strong>The authors accept no responsibility or liability</strong> " +
      "for any damage, data loss (including your sounds and settings) or other harm, whether caused by the " +
      "software, the firmware, a mistake while using it, or anything else.</p>" +
      "<p>Back up your patches before you start. <strong>Everything you do here is at your own risk.</strong></p>",
    checkbox: "I have read this. I understand that I use this software and firmware entirely at my own risk, and that nobody is liable for any damage to my instrument.",
    accept: "Accept and continue",
    accepted: "Accepted for this visit. Reloading the page asks again.",
  },

  backup: {
    heading: "Back up your sounds",
    // (html)
    body:
      "<p>Before you flash anything, back up your patches (sounds) and Multis: open " +
      "<a href=\"{components}\" rel=\"noopener noreferrer\">Novation Components</a>, connect the Summit and save " +
      "all of them to your computer. Write down any Settings you have changed, too.</p>" +
      "<p>A firmware update, modded or official, or a failed flash may change or erase what is stored on the " +
      "synth. Without a backup it may be gone for good.</p>",
    checkbox: "I have backed up all my patches and Multis with Novation Components, and I know where the backup is.",
    confirm: "Confirm backup",
    confirmed: "Backup confirmed for this visit. Reloading the page asks again.",
  },

  steps: {
    download: {
      heading: "1. Download the official firmware",
      // (html)
      body:
        "Download Summit firmware 2.2 directly from Novation. The file is called " +
        "<code>{officialName}</code>. Keep it: you need it to go back to stock.",
      button: "Download official firmware 2.2 from Novation",
    },
    file: {
      heading: "2. Choose the file",
      drop: "Drop the .syx file here, or click to choose it",
      checking: "Checking …",
      official: "Official Summit firmware 2.2 (build 2121), checksum verified.",
      patched:
        "This is an already-modded file. Choose the official file from Novation instead: this page builds " +
        "and checks the mod itself.",
      // {sha} is the file's SHA-256.
      unknown:
        "This is not the file this patcher is made for (SHA-256 {sha}). Only the official Summit firmware 2.2 " +
        "build 2121 works. Download it again with the button above.",
    },
    mod: {
      heading: "3. Build the modded firmware",
      button: "Build {title} {version}",
      // {sha} is the built file's SHA-256.
      ok: "Built and verified: the result matches the expected checksum exactly (SHA-256 {sha}).",
      download: "Download modded .syx (for other flashing tools)",
    },
    flash: {
      heading: "4. Flash it",
      // (html)
      body:
        "Connect the Summit over USB and close Novation Components, your DAW and any other app that uses the " +
        "Summit's MIDI port. Keep the synth powered and the cable plugged in until the page says it's done. " +
        "The synth's own “100%” display runs ahead: wait for this page.",
      modeReal: "My Summit (Web MIDI)",
      modeFake: "Practice with a simulated Summit (sends nothing)",
      flashButton: "Flash modded firmware",
      restoreHeading: "Restore the official firmware",
      // (html)
      restoreBody:
        "Puts the unmodified firmware you chose in step 2 back on the synth, with the same flasher. Use it to " +
        "undo the mod at any time.",
      restoreButton: "Flash official firmware",
      needsBackup: "Confirm your backup above first.",
      needsFile: "Choose the official file in step 2 first.",
      needsMod: "Build the modded firmware in step 3 first.",
      downloadLog: "Download log",
    },
  },

  support: {
    insecure: "Web MIDI needs a secure page (https or localhost).",
    unsupported:
      "This browser has no Web MIDI. Use Chrome or Edge on a computer. Firefox works after it asks you to " +
      "allow MIDI access for this site. Safari doesn't support Web MIDI.",
    denied: "MIDI access with SysEx was not allowed. Allow it in the browser's site settings and try again.",
  },

  confirm: {
    heading: "Flash now?",
    // {question} comes from the flasher, {what} names the file.
    body: "{question} File: {what}. Don't unplug or switch off the synth until this page says it's done.",
    yes: "Flash now",
    no: "Cancel",
  },

  phases: {
    identify: "Talking to the synth …",
    reboot: "Rebooting the synth into its bootloader …",
    transfer: "Sending firmware …",
    restart: "Waiting for the synth to restart …",
    done: "Done.",
  },

  // The big panel after a flash. {version}, {fpga}, {expectedFpga} and {error} are filled in.
  result: {
    ok: {
      title: "Done: the synth is back",
      body: "The firmware was written and the Summit restarted, reporting firmware {version}. Check the boot screen.",
    },
    okMod: "Next: switch MPE on per sound on the VOICE page, and set the zone on the Settings MPE page.",
    okRestore: "The official firmware is back on the synth.",
    mismatch: {
      title: "Restarted, but with another version",
      body: "The Summit restarted but reports firmware {version}, not the version in the file. Check the boot screen, then flash again, starting from the bootloader (see Recovery).",
    },
    noAnswer: {
      title: "Sent, but the synth didn't answer",
      body: "All of the firmware was sent, but the Summit didn't answer afterwards. Switch it off and on and look at the boot screen. If it doesn't start, follow Recovery below.",
    },
    failed: {
      title: "Flashing stopped",
      body: "{error}",
      hint: "Your synth's bootloader is untouched, so this can be fixed: follow Recovery below and flash again from the start. The log below shows what happened; download it if you ask for help.",
    },
    // The synth didn't answer the first identity request (FlashError code "no-identity").
    noIdentity: {
      title: "The synth didn't answer",
      body:
        "The page found the Summit's MIDI port, but no answer came back. Nothing was sent that changes the synth. " +
        "Some browsers stop passing on MIDI from USB devices until they are restarted: quit the browser completely " +
        "(not just this tab or window), open it again, come back to this page and try once more. Also check that " +
        "the Summit is switched on and that no other app (Novation Components, a DAW) is talking to it.",
    },
    cancelled: {
      title: "Cancelled",
      body: "Nothing was sent to the synth.",
    },
    fpgaBehind:
      "Its FPGA reports build {fpga}, older than {expectedFpga}, which goes with firmware 2.2. Open Novation Components: it offers an FPGA update. This page never touches the FPGA.",
    fpgaUnknown: "The FPGA version could not be read. If Novation Components offers an FPGA update, install it.",
    recoveryLink: "Go to Recovery",
  },

  recovery: {
    heading: "Recovery",
    // (html)
    body:
      "<p>The update writes the start-up part of the firmware last and never touches the synth's bootloader. " +
      "So if a flash stops halfway, or the modded firmware doesn't start, the bootloader is still there:</p>" +
      "<ol>" +
      "<li>Switch the Summit off.</li>" +
      "<li>Hold down the <strong>three buttons to the left of the screen</strong> and switch it on.</li>" +
      "<li>The computer now sees a MIDI device called <code>Summit Bootloader</code>.</li>" +
      "<li>Flash the official firmware: use <em>Restore the official firmware</em> above (it detects the " +
      "bootloader), or Novation Components.</li>" +
      "</ol>" +
      "<p>If a transfer stalls, the page stops after 10 seconds without an answer. Power-cycle into the " +
      "bootloader as above and start again from the beginning.</p>",
  },

  footer: {
    // (html)
    body:
      "Source code, documentation and license: <a href=\"{source}\">{source}</a>. Software provided under the MIT " +
      "license, without warranty. Not affiliated with Novation or Focusrite. Patch {title} {version}, built from " +
      "commit <code>{commit}</code>.",
    // (html) A local build, without VITE_SOURCE_URL.
    bodyLocal:
      "Local build. Software provided under the MIT license, without warranty. Not affiliated with Novation or " +
      "Focusrite. Patch {title} {version}, built from commit <code>{commit}</code>.",
  },
};

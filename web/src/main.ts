import "./style.css";
import { contentFor, links } from "./content";
import { parseDescriptor } from "./core/descriptor";
import { identifyFile, patchFirmware, type PatchResult } from "./core/patcher";
import { FakeSummit } from "./flash/fake";
import { EXPECTED_FPGA, flash, FlashError, Plan, type MidiBackend, type Phase } from "./flash/protocol";
import { connectMidi, midiSupport } from "./flash/webmidi";
import { PAGE_PRODUCT as P } from "./product";

const C = contentFor(P);
const d = parseDescriptor(P.descriptor);
document.title = C.title;

// ------------------------------------------------------------------ helpers

const vars: Record<string, string> = {
  summary: d.summary, label: d.label, title: d.title, version: d.version,
  officialName: P.officialFirmwareName, source: links.source, components: links.components, commit: d.built.commit ?? "unknown",
};
const escape = (s: string) => s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
/** Fill {placeholders}; values are escaped, the template itself is trusted (content.ts). */
const fill = (s: string, extra: Record<string, string> = {}) =>
  s.replace(/\{(\w+)\}/g, (_, k) => escape({ ...vars, ...extra }[k] ?? `{${k}}`));

function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {},
  ...children: (Node | string)[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...children);
  return el;
}
const html = (tag: keyof HTMLElementTagNameMap, cls: string, markup: string) => {
  const el = h(tag, { class: cls });
  el.innerHTML = markup;
  return el;
};

const cardBase = "rounded-xl bg-panel p-5 shadow-sm";
const card = `${cardBase} border border-line`;
const btn = "inline-flex items-center justify-center rounded-md px-4 py-2 font-medium transition " +
  "disabled:cursor-not-allowed disabled:opacity-40";
const btnPrimary = `${btn} bg-steel text-steel-ink hover:bg-steel-hover`;
const btnSecondary = `${btn} border border-line bg-panel-2 hover:border-rule`;
/** A card heading as the Peak labels its panel sections: small capitals over
 * a blue rule. "1. Download ..." gets its number on a square key. */
const headingCls = "mb-4 flex items-center gap-3 border-b-2 border-rule pb-1.5 text-sm font-bold uppercase tracking-wider";
const heading = (text: string) => {
  const m = /^(\d+)\.\s+(.*)$/.exec(text);
  if (!m) return h("h2", { class: headingCls }, text);
  return h("h2", { class: headingCls },
    h("span", { class: "flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-steel text-xs font-bold text-steel-ink", "aria-hidden": "true" }, m[1]),
    h("span", {}, m[2]));
};
const chip = (text: string) =>
  h("span", { class: "rounded-sm bg-white/10 px-2.5 py-1 text-xs font-medium ring-1 ring-white/25" }, text);
/** Text as the Peak's display shows it: light on black. */
const display = (text: string) =>
  h("span", { class: "rounded-sm bg-black px-2.5 py-1 font-mono text-xs tracking-wide text-[#dbe7ff] ring-1 ring-deck-rule/60" }, text);
const note = (cls = "") => h("p", { class: `mt-3 text-sm ${cls}`, role: "status" });
const setNote = (el: HTMLElement, text: string, tone: "ok" | "bad" | "info" = "info") => {
  el.textContent = text;
  el.className = "mt-3 text-sm " +
    { ok: "text-ok-ink", bad: "text-bad-ink", info: "text-muted" }[tone];
};

function save(data: Uint8Array, name: string, type = "application/octet-stream") {
  const url = URL.createObjectURL(new Blob([data as Uint8Array<ArrayBuffer>], { type }));
  const a = h("a", { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// -------------------------------------------------------------------- state

const state = {
  accepted: false, // in memory only: a reload asks again
  backedUp: false, // the same
  official: null as Uint8Array | null,
  officialName: "",
  patched: null as PatchResult | null,
  busy: false,
  backend: null as MidiBackend | null,
  log: [] as string[],
};

// -------------------------------------------------------------------- theme

type Theme = "light" | "medium" | "dark";
const THEMES: Theme[] = ["light", "medium", "dark"];
const THEME_KEY = "peak-mpe-theme";

function savedTheme(): Theme | null {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return THEMES.includes(t as Theme) ? (t as Theme) : null;
  } catch {
    return null;
  }
}

const themeButtons = THEMES.map((t) => {
  const b = h("button", { type: "button", "data-theme-choice": t,
    class: "px-2.5 py-1 text-xs font-medium transition" }, C.theme[t]);
  b.addEventListener("click", () => {
    applyTheme(t);
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {
      /* private window: the choice lasts for this visit */
    }
  });
  return b;
});
const themePicker = h("div", { role: "group", "aria-label": C.theme.label,
  class: "inline-flex overflow-hidden rounded-sm ring-1 ring-white/25" }, ...themeButtons);

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  for (const b of themeButtons) {
    const on = b.dataset.themeChoice === t;
    b.setAttribute("aria-pressed", String(on));
    b.className = "px-2.5 py-1 text-xs font-medium transition " +
      (on ? "bg-deck-rule text-deck" : "text-deck-ink/75 hover:bg-white/10 hover:text-deck-ink");
  }
}
applyTheme(savedTheme() ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

// --------------------------------------------------------------------- page

const app = document.getElementById("app")!;
const main = h("main", { class: "mx-auto max-w-3xl space-y-6 px-4 py-8" });
app.append(main);

main.append(
  h("header", { class: "rounded-xl border-x-[10px] border-walnut bg-deck p-6 text-deck-ink shadow-lg sm:p-8" },
    h("div", { class: "flex flex-wrap items-center justify-between gap-3 border-b border-deck-rule pb-2" },
      h("p", { class: "text-xs font-semibold uppercase tracking-widest text-deck-rule" }, C.kicker), themePicker),
    h("h1", { class: "mt-4 text-3xl font-bold tracking-tight sm:text-4xl" }, C.title),
    h("p", { class: "mt-2 max-w-2xl text-deck-ink/85" }, C.subtitle),
    h("div", { class: "mt-5 flex flex-wrap items-center gap-2" }, chip(`${d.title} ${d.version}`), display(d.label),
      chip(C.chips.local))),
  html("div", "rounded-xl border-2 border-rule bg-panel-2 p-4 text-sm", C.banner),
  h("section", { class: card }, heading(C.about.heading), html("div", "prose-lite", fill(C.about.body)),
    ...(links.source ? [html("p", "guide mt-3 text-sm", fill(C.guide, { guideUrl: `${links.source}/blob/main/docs/linnstrument.md` }))] : [])),
);

// Disclaimer: an unticked checkbox, then an explicit button.
const tick = h("input", { type: "checkbox", id: "accept", class: "mt-1 h-4 w-4 shrink-0 accent-steel" });
const acceptBtn = h("button", { class: btnPrimary, disabled: "" }, C.disclaimer.accept);
const acceptNote = note();
main.append(h("section", { class: `${cardBase} border-2 border-bad-line`, id: "disclaimer" },
  heading(C.disclaimer.heading), html("div", "prose-lite", C.disclaimer.body),
  h("label", { for: "accept", class: "mt-4 flex gap-3 text-sm font-medium" }, tick, C.disclaimer.checkbox),
  h("div", { class: "mt-4" }, acceptBtn), acceptNote));
tick.addEventListener("change", () => (acceptBtn.disabled = !tick.checked || state.accepted));

// Everything that touches firmware sits in this fieldset until accepted.
const gated = h("fieldset", { class: "space-y-6 transition", disabled: "" });
main.append(gated);

// Backup: like the disclaimer, an unticked checkbox, then an explicit button.
const backupTick = h("input", { type: "checkbox", id: "backup", class: "mt-1 h-4 w-4 shrink-0 accent-steel" });
const backupBtn = h("button", { class: btnPrimary, disabled: "" }, C.backup.confirm);
const backupNote = note();
gated.append(h("section", { class: `${cardBase} border-2 border-rule`, id: "backup-card" },
  heading(C.backup.heading), html("div", "prose-lite", fill(C.backup.body)),
  h("label", { for: "backup", class: "mt-4 flex gap-3 text-sm font-medium" }, backupTick, C.backup.checkbox),
  h("div", { class: "mt-4" }, backupBtn), backupNote));
backupTick.addEventListener("change", () => (backupBtn.disabled = !backupTick.checked || state.backedUp));

// 1. Download
gated.append(h("section", { class: card }, heading(C.steps.download.heading),
  html("p", "", fill(C.steps.download.body)),
  h("p", { class: "mt-4" }, h("a", { class: btnSecondary, href: P.officialFirmware, rel: "noopener noreferrer" },
    C.steps.download.button))));

// 2. File
const fileInput = h("input", { type: "file", accept: ".syx", class: "sr-only", id: "file" });
const drop = h("label", { for: "file", class: "flex cursor-pointer items-center justify-center rounded-lg border-2 " +
  "border-dashed border-line bg-panel-2 p-8 text-center text-muted hover:border-rule" },
C.steps.file.drop);
const fileNote = note();
gated.append(h("section", { class: card }, heading(C.steps.file.heading), fileInput, drop, fileNote));

// 3. Mod
const modBtn = h("button", { class: btnPrimary, disabled: "" }, fill(C.steps.mod.button));
const modNote = note();
const modDownload = h("button", { class: btnSecondary, disabled: "" }, C.steps.mod.download);
gated.append(h("section", { class: card }, heading(C.steps.mod.heading),
  h("div", { class: "flex flex-wrap gap-3" }, modBtn, modDownload), modNote));

// 4. Flash
const support = midiSupport();
const modeReal = h("input", { type: "radio", name: "mode", value: "real", class: "accent-steel" });
const modeFake = h("input", { type: "radio", name: "mode", value: "fake", class: "accent-steel" });
if (support === "ok") modeReal.checked = true;
else {
  modeFake.checked = true;
  modeReal.disabled = true;
}
const supportNote = note();
if (support !== "ok") setNote(supportNote, C.support[support], "bad");
const flashGate = note();
const flashBtn = h("button", { class: btnPrimary, disabled: "" }, C.steps.flash.flashButton);
const restoreBtn = h("button", { class: btnPrimary, disabled: "" }, C.steps.flash.restoreButton);
const phaseText = h("p", { class: "text-sm font-medium" });
const bar = h("div", { class: "h-full w-0 bg-steel transition-[width]" });
const counter = h("p", { class: "text-xs tabular-nums text-muted" });
const resultBox = h("div", { class: "mt-4 hidden", role: "alert" });
const logBox = h("pre", { class: "mt-3 max-h-48 overflow-auto rounded-sm bg-black p-3 font-mono text-xs text-[#dbe7ff]" });
const logBtn = h("button", { class: `${btnSecondary} mt-3 text-sm`, disabled: "" }, C.steps.flash.downloadLog);
const progress = h("div", { class: "mt-4 hidden space-y-2" }, phaseText,
  h("div", { class: "h-3 overflow-hidden rounded-sm bg-panel-2 ring-1 ring-line" }, bar), counter);

gated.append(h("section", { class: card, id: "flash" }, heading(C.steps.flash.heading),
  html("p", "", C.steps.flash.body),
  h("div", { class: "mt-4 flex flex-col gap-2 text-sm" },
    h("label", { class: "flex items-center gap-2" }, modeReal, C.steps.flash.modeReal),
    h("label", { class: "flex items-center gap-2" }, modeFake, C.steps.flash.modeFake)),
  supportNote, flashGate,
  h("div", { class: "mt-4 flex flex-wrap gap-3" }, flashBtn),
  h("div", { class: "mt-6 rounded-lg border border-line bg-panel-2 p-4" },
    h("h3", { class: "font-semibold" }, C.steps.flash.restoreHeading),
    html("p", "mt-1 text-sm", C.steps.flash.restoreBody), h("div", { class: "mt-3" }, restoreBtn)),
  progress, resultBox, logBox, logBtn));

main.append(h("section", { class: card, id: "recovery" }, heading(C.recovery.heading), html("div", "prose-lite", C.recovery.body)));
main.append(html("footer", "pb-8 text-xs text-muted", fill(links.source ? C.footer.body : C.footer.bodyLocal)));

// ---------------------------------------------------------------- behaviour

function refresh() {
  gated.disabled = !state.accepted || state.busy;
  gated.classList.toggle("opacity-50", !state.accepted);
  const official = state.official !== null;
  modBtn.disabled = !official || state.patched !== null;
  modDownload.disabled = state.patched === null;
  flashBtn.disabled = state.patched === null || !state.backedUp;
  flashBtn.title = !state.backedUp ? C.steps.flash.needsBackup : state.patched ? "" : C.steps.flash.needsMod;
  restoreBtn.disabled = !official || !state.backedUp;
  restoreBtn.title = !state.backedUp ? C.steps.flash.needsBackup : official ? "" : C.steps.flash.needsFile;
  setNote(flashGate, state.backedUp ? "" : C.steps.flash.needsBackup, "bad");
  logBtn.disabled = state.log.length === 0 || state.busy;
}

backupBtn.addEventListener("click", () => {
  if (!backupTick.checked) return;
  state.backedUp = true;
  backupTick.disabled = true;
  backupBtn.disabled = true;
  setNote(backupNote, C.backup.confirmed, "ok");
  refresh();
});

acceptBtn.addEventListener("click", () => {
  if (!tick.checked) return;
  state.accepted = true;
  tick.disabled = true;
  acceptBtn.disabled = true;
  setNote(acceptNote, C.disclaimer.accepted, "ok");
  refresh();
});

async function takeFile(file: File) {
  state.official = null;
  state.patched = null;
  refresh();
  setNote(fileNote, C.steps.file.checking);
  const data = new Uint8Array(await file.arrayBuffer());
  const id = await identifyFile(data, d);
  if (id.kind === "official") {
    state.official = data;
    state.officialName = file.name;
    setNote(fileNote, C.steps.file.official, "ok");
  } else if (id.kind === "patched") {
    setNote(fileNote, C.steps.file.patched, "bad");
  } else {
    setNote(fileNote, fill(C.steps.file.unknown, { sha: id.sha256 }), "bad");
  }
  setNote(modNote, "");
  refresh();
}

fileInput.addEventListener("change", () => fileInput.files?.[0] && takeFile(fileInput.files[0]));
drop.addEventListener("dragover", (e) => e.preventDefault());
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer?.files[0];
  if (f && state.accepted && !state.busy) void takeFile(f);
});

modBtn.addEventListener("click", async () => {
  if (!state.official) return;
  try {
    state.patched = await patchFirmware(state.official, d);
    setNote(modNote, fill(C.steps.mod.ok, { sha: state.patched.sha256 }), "ok");
  } catch (e) {
    state.patched = null;
    setNote(modNote, (e as Error).message, "bad");
  }
  refresh();
});
modDownload.addEventListener("click", () => state.patched && save(state.patched.syx, state.patched.fileName));

// A modal for the flasher's confirmation question.
function ask(question: string, what: string): Promise<boolean> {
  const dlg = h("dialog", { class: "m-auto max-w-md rounded-xl border border-line bg-panel p-6 text-ink backdrop:bg-black/60" });
  const yes = h("button", { class: btnPrimary }, C.confirm.yes);
  const no = h("button", { class: btnSecondary, autofocus: "" }, C.confirm.no);
  dlg.append(h("h2", { class: "text-lg font-semibold" }, C.confirm.heading),
    h("p", { class: "mt-2 text-sm" }, fill(C.confirm.body, { question, what })),
    h("div", { class: "mt-5 flex justify-end gap-3" }, no, yes));
  document.body.append(dlg);
  return new Promise((resolve) => {
    const done = (v: boolean) => {
      dlg.close();
      dlg.remove();
      resolve(v);
    };
    yes.addEventListener("click", () => done(true));
    no.addEventListener("click", () => done(false));
    dlg.addEventListener("cancel", () => done(false));
    dlg.showModal();
  });
}

async function backend(): Promise<MidiBackend> {
  if (modeFake.checked)
    return new FakeSummit({ product: P.name, version: P.stockVersion, fpga: P.expectedFpga,
      bootDelayMs: 900, eraseMs: 3400, requestDelayMs: 0, repeatEvery: 40, appDelayMs: 2100, slowBoot: 1 });
  if (!state.backend) {
    try {
      state.backend = await connectMidi();
    } catch {
      throw new Error(C.support.denied);
    }
  }
  return state.backend;
}

type Tone = "ok" | "warn" | "bad";
const tones: Record<Tone, { box: string; icon: string }> = {
  ok: { box: "border-ok-line bg-ok-bg text-ok-ink", icon: "✓" },
  warn: { box: "border-warn-line bg-warn-bg text-warn-ink", icon: "!" },
  bad: { box: "border-bad-line bg-bad-bg text-bad-ink", icon: "✕" },
};

/** The big result panel: a title, what happened, and what to do next. */
function showResult(tone: Tone, title: string, lines: string[], recovery = false) {
  const t = tones[tone];
  resultBox.className = `mt-4 rounded-xl border-2 p-5 ${t.box}`;
  const body = h("div", { class: "space-y-2" }, h("h3", { class: "text-xl font-bold" }, title),
    ...lines.filter(Boolean).map((l) => h("p", {}, l)));
  if (recovery) body.append(h("p", {}, h("a", { href: "#recovery", class: "font-semibold underline" }, C.result.recoveryLink)));
  resultBox.replaceChildren(h("div", { class: "flex gap-4" },
    h("span", { class: "flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 border-current text-xl font-bold", "aria-hidden": "true" }, t.icon),
    body));
  resultBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

const leaveGuard = (e: BeforeUnloadEvent) => e.preventDefault();

async function run(data: Uint8Array, what: string, kind: "mod" | "restore") {
  if (!state.accepted || !state.backedUp || state.busy) return;
  state.busy = true;
  state.log = [];
  logBox.textContent = "";
  resultBox.classList.add("hidden");
  progress.classList.remove("hidden");
  bar.style.width = "0%";
  refresh();
  window.addEventListener("beforeunload", leaveGuard);
  const t0 = performance.now();
  const line = (s: string) => {
    state.log.push(`${((performance.now() - t0) / 1000).toFixed(3).padStart(9)} ${s}`);
  };
  const say = (s: string) => {
    line(s);
    logBox.textContent += `${s}\n`;
    logBox.scrollTop = logBox.scrollHeight;
  };
  try {
    const plan = new Plan(data);
    say(modeFake.checked ? `practice mode: simulated ${P.name}, no MIDI is sent` : "Web MIDI");
    let lastPaint = 0;
    const r = await flash(plan, await backend(), {
      log: say,
      phase: (p: Phase) => (phaseText.textContent = C.phases[p]),
      progress: (sent, total) => {
        const now = performance.now();
        if (now - lastPaint < 50 && sent < total) return;
        lastPaint = now;
        bar.style.width = `${(100 * sent) / total}%`;
        counter.textContent = `${sent} / ${total}`;
      },
      confirm: (q) => ask(q, what),
      midi: (dir, port, msg) => line(`${dir} ${port} ${Array.from(msg, (b) => b.toString(16).padStart(2, "0")).join(" ")}`),
    });
    const fpgaLine = r.version === null ? "" : r.fpgaBehind
      ? fill(C.result.fpgaBehind, { fpga: String(r.fpga), expectedFpga: String(EXPECTED_FPGA[plan.product]) })
      : r.fpga === null ? C.result.fpgaUnknown : "";
    if (r.version === null) showResult("bad", C.result.noAnswer.title, [C.result.noAnswer.body], true);
    else if (!r.matchesFile)
      showResult("warn", C.result.mismatch.title, [fill(C.result.mismatch.body, { version: r.version }), fpgaLine], true);
    else showResult(r.fpgaBehind ? "warn" : "ok", C.result.ok.title,
      [fill(C.result.ok.body, { version: r.version }), kind === "mod" ? C.result.okMod : C.result.okRestore, fpgaLine]);
  } catch (e) {
    const msg = (e as Error).message;
    say(`error: ${msg}`);
    if (msg === "not confirmed") showResult("warn", C.result.cancelled.title, [C.result.cancelled.body]);
    else if (e instanceof FlashError && e.code === "no-identity")
      showResult("warn", C.result.noIdentity.title, [C.result.noIdentity.body]);
    else showResult("bad", C.result.failed.title, [fill(C.result.failed.body, { error: msg }), C.result.failed.hint], true);
  } finally {
    window.removeEventListener("beforeunload", leaveGuard);
    state.busy = false;
    refresh();
  }
}

flashBtn.addEventListener("click", () => state.patched && run(state.patched.syx, `${d.title} ${d.version} (${state.patched.fileName})`, "mod"));
restoreBtn.addEventListener("click", () => state.official && run(state.official, `official firmware (${state.officialName})`, "restore"));
logBtn.addEventListener("click", () => save(new TextEncoder().encode(state.log.join("\n") + "\n"), `${P.id}-flash-log.txt`, "text/plain"));

refresh();

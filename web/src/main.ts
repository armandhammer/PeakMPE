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

const card = "rounded-xl border border-stone-200 bg-white p-5 shadow-sm dark:border-stone-800 dark:bg-stone-900";
const btn = "inline-flex items-center justify-center rounded-lg px-4 py-2 font-medium transition " +
  "disabled:cursor-not-allowed disabled:opacity-40";
const btnPrimary = `${btn} bg-amber-600 text-white hover:bg-amber-700`;
const btnSecondary = `${btn} border border-stone-300 hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800`;
/** A card heading; "1. Download ..." gets its number as a round badge. */
const heading = (text: string) => {
  const m = /^(\d+)\.\s+(.*)$/.exec(text);
  if (!m) return h("h2", { class: "mb-3 text-lg font-semibold" }, text);
  return h("h2", { class: "mb-3 flex items-center gap-3 text-lg font-semibold" },
    h("span", { class: "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-600 text-sm font-bold text-white", "aria-hidden": "true" }, m[1]),
    h("span", {}, m[2]));
};
const chip = (text: string) =>
  h("span", { class: "rounded-full bg-white/15 px-3 py-1 text-xs font-medium ring-1 ring-white/30" }, text);
const note = (cls = "") => h("p", { class: `mt-3 text-sm ${cls}`, role: "status" });
const setNote = (el: HTMLElement, text: string, tone: "ok" | "bad" | "info" = "info") => {
  el.textContent = text;
  el.className = "mt-3 text-sm " +
    { ok: "text-emerald-700 dark:text-emerald-400", bad: "text-red-700 dark:text-red-400", info: "text-stone-600 dark:text-stone-400" }[tone];
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

// --------------------------------------------------------------------- page

const app = document.getElementById("app")!;
const main = h("main", { class: "mx-auto max-w-3xl space-y-6 px-4 py-8" });
app.append(main);

main.append(
  h("header", { class: "rounded-2xl bg-linear-to-br from-amber-500 via-orange-600 to-rose-700 p-6 text-white shadow-lg sm:p-8" },
    h("p", { class: "text-xs font-semibold uppercase tracking-widest text-white/80" }, C.kicker),
    h("h1", { class: "mt-2 text-3xl font-bold tracking-tight sm:text-4xl" }, C.title),
    h("p", { class: "mt-2 max-w-2xl text-white/90" }, C.subtitle),
    h("div", { class: "mt-5 flex flex-wrap gap-2" }, chip(`${d.title} ${d.version}`), chip(`Boot screen: ${d.label}`),
      chip("Nothing uploaded: patched in your browser"))),
  html("div", "rounded-xl border-2 border-amber-500 bg-amber-50 p-4 text-sm dark:bg-amber-950/40", C.banner),
  h("section", { class: card }, heading(C.about.heading), html("div", "prose-lite", fill(C.about.body)),
    ...(links.source ? [html("p", "mt-3 text-sm", fill(C.guide, { guideUrl: `${links.source}/blob/main/docs/linnstrument.md` }))] : [])),
);

// Disclaimer: an unticked checkbox, then an explicit button.
const tick = h("input", { type: "checkbox", id: "accept", class: "mt-1 h-4 w-4 shrink-0 accent-amber-600" });
const acceptBtn = h("button", { class: btnPrimary, disabled: "" }, C.disclaimer.accept);
const acceptNote = note();
main.append(h("section", { class: `${card} border-2 border-red-300 dark:border-red-900`, id: "disclaimer" },
  heading(C.disclaimer.heading), html("div", "prose-lite", C.disclaimer.body),
  h("label", { for: "accept", class: "mt-4 flex gap-3 text-sm font-medium" }, tick, C.disclaimer.checkbox),
  h("div", { class: "mt-4" }, acceptBtn), acceptNote));
tick.addEventListener("change", () => (acceptBtn.disabled = !tick.checked || state.accepted));

// Everything that touches firmware sits in this fieldset until accepted.
const gated = h("fieldset", { class: "space-y-6 transition", disabled: "" });
main.append(gated);

// Backup: like the disclaimer, an unticked checkbox, then an explicit button.
const backupTick = h("input", { type: "checkbox", id: "backup", class: "mt-1 h-4 w-4 shrink-0 accent-amber-600" });
const backupBtn = h("button", { class: btnPrimary, disabled: "" }, C.backup.confirm);
const backupNote = note();
gated.append(h("section", { class: `${card} border-2 border-amber-300 dark:border-amber-900`, id: "backup-card" },
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
  "border-dashed border-stone-300 p-8 text-center text-stone-600 hover:border-amber-500 dark:border-stone-700 dark:text-stone-400" },
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
const modeReal = h("input", { type: "radio", name: "mode", value: "real", class: "accent-amber-600" });
const modeFake = h("input", { type: "radio", name: "mode", value: "fake", class: "accent-amber-600" });
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
const bar = h("div", { class: "h-full w-0 bg-amber-600 transition-[width]" });
const counter = h("p", { class: "text-xs tabular-nums text-stone-500" });
const resultBox = h("div", { class: "mt-4 hidden", role: "alert" });
const logBox = h("pre", { class: "mt-3 max-h-48 overflow-auto rounded bg-stone-100 p-3 text-xs dark:bg-stone-950" });
const logBtn = h("button", { class: `${btnSecondary} mt-3 text-sm`, disabled: "" }, C.steps.flash.downloadLog);
const progress = h("div", { class: "mt-4 hidden space-y-2" }, phaseText,
  h("div", { class: "h-3 overflow-hidden rounded bg-stone-200 dark:bg-stone-800" }, bar), counter);

gated.append(h("section", { class: card, id: "flash" }, heading(C.steps.flash.heading),
  html("p", "", C.steps.flash.body),
  h("div", { class: "mt-4 flex flex-col gap-2 text-sm" },
    h("label", { class: "flex items-center gap-2" }, modeReal, C.steps.flash.modeReal),
    h("label", { class: "flex items-center gap-2" }, modeFake, C.steps.flash.modeFake)),
  supportNote, flashGate,
  h("div", { class: "mt-4 flex flex-wrap gap-3" }, flashBtn),
  h("div", { class: "mt-6 rounded-lg border border-stone-200 p-4 dark:border-stone-800" },
    h("h3", { class: "font-semibold" }, C.steps.flash.restoreHeading),
    html("p", "mt-1 text-sm", C.steps.flash.restoreBody), h("div", { class: "mt-3" }, restoreBtn)),
  progress, resultBox, logBox, logBtn));

main.append(h("section", { class: card, id: "recovery" }, heading(C.recovery.heading), html("div", "prose-lite", C.recovery.body)));
main.append(html("footer", "pb-8 text-xs text-stone-500", fill(links.source ? C.footer.body : C.footer.bodyLocal)));

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
  const dlg = h("dialog", { class: "m-auto max-w-md rounded-xl p-6 backdrop:bg-black/50 dark:bg-stone-900 dark:text-stone-100" });
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
  ok: { box: "border-emerald-500 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/50 dark:text-emerald-100", icon: "✓" },
  warn: { box: "border-amber-500 bg-amber-50 text-amber-950 dark:bg-amber-950/50 dark:text-amber-100", icon: "!" },
  bad: { box: "border-red-500 bg-red-50 text-red-950 dark:bg-red-950/50 dark:text-red-100", icon: "✕" },
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

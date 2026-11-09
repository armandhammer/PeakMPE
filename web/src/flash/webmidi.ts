// Web MIDI transport for protocol.ts. Needs SysEx permission: Chrome and Edge
// ask for it; Firefox asks to install a site permission add-on; Safari has no
// Web MIDI. Only called after the user clicks "Connect".

import type { MidiBackend, MidiPort } from "./protocol";

export type MidiSupport = "ok" | "insecure" | "unsupported";

export function midiSupport(): MidiSupport {
  if (!window.isSecureContext) return "insecure";
  return "requestMIDIAccess" in navigator ? "ok" : "unsupported";
}

export async function connectMidi(): Promise<MidiBackend> {
  const access = await navigator.requestMIDIAccess({ sysex: true });
  return new WebMidiBackend(access);
}

class WebMidiBackend implements MidiBackend {
  constructor(private readonly access: MIDIAccess) {}

  private inputs() {
    return [...this.access.inputs.values()].filter((p) => p.state === "connected");
  }

  private outputs() {
    return [...this.access.outputs.values()].filter((p) => p.state === "connected");
  }

  portNames(): string[] {
    const outs = new Set(this.outputs().map((p) => p.name ?? ""));
    return this.inputs().map((p) => p.name ?? "").filter((n) => n && outs.has(n));
  }

  async open(name: string): Promise<MidiPort> {
    const input = this.inputs().find((p) => p.name === name);
    const output = this.outputs().find((p) => p.name === name);
    if (!input || !output) throw new Error(`MIDI port "${name}" is gone`);
    await Promise.all([input.open(), output.open()]);
    const inbox: Uint8Array[] = [];
    let waiter: ((m: Uint8Array | null) => void) | null = null;
    input.onmidimessage = (e: MIDIMessageEvent) => {
      if (!e.data) return;
      const msg = new Uint8Array(e.data);
      if (msg[0] === 0xf8 || msg[0] === 0xfe) return; // clock, active sensing
      if (waiter) waiter(msg);
      else inbox.push(msg);
    };
    return {
      name,
      send: (msg) => output.send(msg),
      receive: (timeoutMs) => {
        const m = inbox.shift();
        if (m) return Promise.resolve(m);
        return new Promise((resolve) => {
          const timer = setTimeout(() => {
            waiter = null;
            resolve(null);
          }, timeoutMs);
          waiter = (msg) => {
            clearTimeout(timer);
            waiter = null;
            resolve(msg);
          };
        });
      },
      close: async () => {
        input.onmidimessage = null;
        waiter?.(null);
        await Promise.all([input.close(), output.close()]);
      },
    };
  }
}

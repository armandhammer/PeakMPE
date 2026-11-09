// SHA-256 with WebCrypto (browsers on https or localhost, and Node >= 19).

export async function sha256(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data as Uint8Array<ArrayBuffer>);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function base64ToBytes(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function hexToBytes(s: string): Uint8Array {
  if (!/^([0-9a-fA-F]{2})*$/.test(s)) throw new Error(`not a hex string: ${s}`);
  return Uint8Array.from(s.match(/../g) ?? [], (h) => parseInt(h, 16));
}

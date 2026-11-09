#!/usr/bin/env bash
# Decode a firmware .syx into work/ and produce a Thumb-2 disassembly.
#
#   scripts/disasm.sh firmware/summit-firmware-2.2-build2121.syx
#
# Writes work/<name>.bin (flat image), work/<name>.elf (image wrapped at the
# load base) and work/<name>.dis. Runs in the dev image (scripts/dev), which
# has llvm-objcopy/llvm-objdump (LLVM_BIN overrides their directory). The
# base defaults to 0x0800C000, which tools/find_base.py confirms for Peak 2.2
# and Summit 2.2.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${SUMMIT_MPE_IN_IMAGE:-}" == 1 ]] || exec "$repo_root/scripts/dev" "$repo_root/scripts/disasm.sh" "$@"
syx="${1:?usage: scripts/disasm.sh FILE.syx}"
base="${BASE:-0x0800C000}"
llvm="${LLVM_BIN:-/opt/homebrew/opt/llvm/bin}"
name="$(basename "${syx%.syx}")"
out="$repo_root/work"

for tool in llvm-objcopy llvm-objdump; do
    [[ -x "$llvm/$tool" ]] || { echo "missing $llvm/$tool (set LLVM_BIN)" >&2; exit 1; }
done
mkdir -p "$out"

python3 -I "$repo_root/tools/syx.py" decode "$syx" "$out/$name.bin"
# objcopy derives symbol names from the input path, so run it from work/.
(cd "$out" && "$llvm/llvm-objcopy" -I binary -O elf32-littlearm \
    --rename-section .data=.text,alloc,load,readonly,code,contents \
    "$name.bin" "$name.elf")
"$llvm/llvm-objdump" -d --triple=thumbv7em-none-eabi --mcpu=cortex-m4 \
    --no-show-raw-insn --adjust-vma="$base" "$out/$name.elf" \
    | sed -E 's/ <_binary[^>]*>//' > "$out/$name.dis"
echo "wrote $out/$name.dis ($(wc -l < "$out/$name.dis" | tr -d ' ') lines, base $base)"

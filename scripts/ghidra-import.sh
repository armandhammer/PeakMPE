#!/usr/bin/env bash
# Import a firmware .syx into a headless Ghidra project under work/ghidra/.
#
#   scripts/ghidra-import.sh firmware/summit-firmware-2.2-build2121.syx
#   scripts/ghidra-import.sh FILE.syx --decompile 0x0801d9bc 0x08021314
#   scripts/ghidra-import.sh FILE.syx --decompile-all   # work/decomp/<name>-all.c
#
# The image is loaded as ARM Cortex (Thumb) little-endian at BASE (default
# 0x0800C000). tools/ghidra/SetupCortexM.java adds RAM/peripheral blocks and
# vector-table entry points before auto-analysis; afterwards the matching
# docs/symbols/<product>-<version>-<build>.csv (or SYMBOLS=path) is applied.
# Re-running replaces the program. Needs GHIDRA_INSTALL_DIR and a JDK 21
# (see docs/SETUP.md).
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
syx="${1:?usage: scripts/ghidra-import.sh FILE.syx [--decompile ADDR... | --decompile-all]}"
shift
base="${BASE:-0x0800C000}"
ghidra="${GHIDRA_INSTALL_DIR:-$HOME/tools/ghidra_12.1.4_PUBLIC}"  # default of scripts/install-ghidra.sh
[[ -x "$ghidra/support/analyzeHeadless" ]] || { echo "Ghidra not found at $ghidra; set GHIDRA_INSTALL_DIR (see docs/SETUP.md)" >&2; exit 1; }
name="$(basename "${syx%.syx}")"
work="$repo_root/work"
project_dir="$work/ghidra"
# summit-firmware-2.2-build2121 -> docs/symbols/summit-2.2-2121.csv
symbols="${SYMBOLS:-$repo_root/docs/symbols/$(echo "$name" | sed -E 's/-firmware-([0-9.]+)-build([0-9]+)$/-\1-\2/').csv}"
post=()
[[ -f "$symbols" ]] && post=(-postScript ApplySymbols.java "$symbols")

if [[ -z "${JAVA_HOME:-}" && -d /opt/homebrew/opt/openjdk@21 ]]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
fi

mkdir -p "$project_dir"
python3 -I "$repo_root/tools/syx.py" decode "$syx" "$work/$name.bin"

"$ghidra/support/analyzeHeadless" "$project_dir" SummitMPE \
    -import "$work/$name.bin" -overwrite \
    -loader BinaryLoader -loader-baseAddr "$base" \
    -processor ARM:LE:32:Cortex \
    -scriptPath "$repo_root/tools/ghidra" \
    -preScript SetupCortexM.java "${post[@]}" \
    -log "$work/ghidra-import.log" 2>&1 | grep -E "SetupCortexM:|ApplySymbols:|ERROR|Import succeeded" || true

if [[ "${1:-}" == "--decompile" ]]; then
    shift
    "$ghidra/support/analyzeHeadless" "$project_dir" SummitMPE \
        -process "$name.bin" -noanalysis -readOnly \
        -scriptPath "$repo_root/tools/ghidra" \
        -postScript DecompileAt.java "$work/decomp/$name" "$@" 2>&1 \
        | grep -oE "DECOMPILE .*\.c|ERROR.*" | sed -E 's/^DECOMPILE //; s/ \(GhidraScript\).*//' || true
fi

if [[ "${1:-}" == "--decompile-all" ]]; then
    "$ghidra/support/analyzeHeadless" "$project_dir" SummitMPE \
        -process "$name.bin" -noanalysis -readOnly \
        -scriptPath "$repo_root/tools/ghidra" \
        -postScript DecompileAll.java "$work/decomp/$name-all.c" 2>&1 \
        | grep -oE "DECOMPILE_ALL .*|ERROR.*" | sed -E 's/ \(GhidraScript\).*//' || true
fi

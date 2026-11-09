#!/usr/bin/env bash
# Report whether the tools this repository uses are present, with versions.
# Exits non-zero if a required one is missing. See docs/SETUP.md.
#
# Required on the host: git, Docker (builds and tests run in the dev image,
# scripts/dev) and the firmware. Optional: the git hooks; native on the Mac, the
# hardware venv (tools/flash.py, tools/midirec.py, tools/hwrig) and the
# reverse-engineering tools (Ghidra, its JDK, Node for the REA MCP server).
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
java_home="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
ghidra="${GHIDRA_INSTALL_DIR:-$HOME/tools/ghidra_12.1.4_PUBLIC}"  # default of scripts/install-ghidra.sh
missing=0

row() { printf '%-8s %-24s %s\n' "$1" "$2" "$3"; }
need() {  # need <name> <version or empty> [hint]: required
    if [[ -n "$2" ]]; then row ok "$1" "$2"; else row MISSING "$1" "${3:-}"; missing=1; fi
}
opt() {   # opt <name> <version or empty> [hint]: optional, never fails
    if [[ -n "$2" ]]; then row ok "$1" "$2"; else row "--" "$1" "not installed (optional${3:+: $3})"; fi
}

echo "Host (required)"
need git "$(git --version 2>/dev/null | cut -d' ' -f3)"
need docker "$(docker version -f '{{.Client.Version}}' 2>/dev/null)" "Docker Desktop, OrbStack or Colima"
need "docker daemon" "$(docker version -f '{{.Server.Version}} ({{.Server.Os}}/{{.Server.Arch}})' 2>/dev/null)" "start Docker"
hooks="$(git -C "$repo_root" config core.hooksPath 2>/dev/null)"
opt "git hooks" "$([[ "$hooks" == ".githooks" ]] && echo "$hooks")" "scripts/install-hooks.sh"
if [[ -f "$repo_root/firmware/SHA256SUMS" ]]; then
    (cd "$repo_root/firmware" && shasum -a 256 -c SHA256SUMS --quiet) && row ok firmware "hashes match firmware/SHA256SUMS"
else
    row MISSING firmware "run scripts/fetch-firmware.sh"
    missing=1
fi

echo
echo "Dev image (scripts/dev)"
if docker info >/dev/null 2>&1; then
    if fp="$("$repo_root/scripts/dev" --fingerprint 2>/dev/null)"; then
        row ok image "$("$repo_root/scripts/dev" --image)"
        grab() { grep -m1 -E "$1" <<< "$fp" | grep -oE "$2" | head -1; }
        need arm-none-eabi-gcc "$(grab '^arm-none-eabi-gcc' '[0-9]+\.[0-9]+\.[0-9]+')"
        need arm-none-eabi-ld "$(grab 'GNU ld' '[0-9]+\.[0-9.]+')"
        need llvm-objdump "$(grab 'LLVM version' '[0-9]+\.[0-9.]+')"
        need python "$(grab '^Python ' '[0-9]+\.[0-9.]+')"
        for p in unicorn pytest pytest_xdist numpy; do
            need "$p" "$(grep -m1 -iE "^${p//_/[-_]}==" <<< "$fp" | cut -d= -f3)"
        done
        need node "$(grab '^node ' 'v[0-9.]+')"
    else
        need image "" "scripts/dev --build failed; run it to see why"
    fi
else
    row "--" image "not checked: Docker isn't running"
fi

echo
echo "Native (optional)"
# The hardware venv: this checkout's, or (in a worktree) the main checkout's.
venv_py="$repo_root/.venv/bin/python"
[[ -x "$venv_py" ]] || venv_py="$(dirname "$(git -C "$repo_root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")/.venv/bin/python"
hw="flash, midirec, hwrig: requirements-hw.txt"
opt "python3 (hardware)" "$(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null)" "$hw"
opt ".venv python-rtmidi" "$("$venv_py" -I -c 'import rtmidi; print(rtmidi.version.version)' 2>/dev/null)" "$hw"
opt ".venv numpy" "$("$venv_py" -I -c 'import numpy; print(numpy.__version__)' 2>/dev/null)" "$hw"
opt ".venv sounddevice" "$("$venv_py" -I -c 'import sounddevice; print(sounddevice.__version__)' 2>/dev/null)" "$hw"
opt ".venv unicorn" "$("$venv_py" -I -c 'import unicorn; print(unicorn.__version__)' 2>/dev/null)" "$hw"
opt "JDK 21+" "$("$java_home/bin/java" -version 2>&1 | head -1 | grep -oE '"[0-9.]+' | tr -d '"')" "Ghidra, brew bundle"
if [[ -n "$ghidra" && -f "$ghidra/Ghidra/application.properties" ]]; then
    opt Ghidra "$(grep -m1 '^application.version=' "$ghidra/Ghidra/application.properties" | cut -d= -f2) ($ghidra)"
else
    opt Ghidra "" "scripts/install-ghidra.sh"
fi
opt "node (REA MCP)" "$(node --version 2>/dev/null)" "brew bundle"

exit "$missing"

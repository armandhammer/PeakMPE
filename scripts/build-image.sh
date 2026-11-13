#!/usr/bin/env bash
# Build a verified image to flash, and print the recovery steps and the flash
# commands (docs/hardware.md). It never flashes: the user runs the printed
# commands and types the confirmation themselves.
#
#   scripts/build-image.sh                                 patches/mpe/patch.py
#   scripts/build-image.sh patches/version_string.py       another definition
#   scripts/build-image.sh --skip-checks                   skip scripts/check
#
# Steps, each one a stop on failure:
#   1. scripts/check, the full suite with the firmware (unless --skip-checks);
#   2. build with tools/patch.py <definition> --verify in the dev image and
#      check the file's SHA-256 against the one the build printed;
#   3. copy the image to work/flash/<name>-<sha12>.syx, which no later build
#      overwrites, so the flash commands point at exactly this file;
#   4. print the commit, the recovery steps and the zsh-safe flash.py commands.
set -euo pipefail

die() { echo "build-image: $*" >&2; exit 1; }

checks=yes
definition=patches/mpe/patch.py
for a in "$@"; do
    case "$a" in
        --skip-checks) checks=no ;;
        -*) die "usage: scripts/build-image.sh [--skip-checks] [definition]" ;;
        *) definition="$a" ;;
    esac
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ -f "$definition" ]] || die "no patch definition $definition"
[[ -e firmware/summit-firmware-2.2-build2121.syx ]] || die "no official firmware in firmware/: scripts/fetch-firmware.sh"

commit="$(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
dirty=""
[[ -z "$(git status --porcelain 2>/dev/null)" ]] || dirty=" plus uncommitted changes"

# 1. The checks.
if [[ $checks == yes ]]; then
    scripts/check || die "scripts/check failed; nothing built"
else
    echo "== --skip-checks: scripts/check not run"
fi

# 2. Build.
log="$(mktemp -t build-image.XXXXXX)"
trap 'rm -f "$log"' EXIT
scripts/dev python -I tools/patch.py "$definition" --verify | tee "$log" || die "build failed"
image="$(sed -n 's/^wrote  *//p' "$log" | tail -1)"
claimed="$(sed -n 's/^sha256  *//p' "$log" | tail -1)"
source="$(sed -n 's/^source  *\([^ ]*\).*/\1/p' "$log" | tail -1)"
[[ -n "$image" && -f "$image" ]] || die "build printed no image path"
grep -qx 'verify  ok' "$log" || grep -q '^verify  nothing to check' "$log" || die "build did not verify"
sha="$(shasum -a 256 < "$image" | cut -d' ' -f1)"
[[ "$sha" == "$claimed" ]] || die "SHA-256 of $image is $sha, the build printed $claimed"
size="$(wc -c < "$image" | tr -d ' ')"

# 3. The copy the flash uses.
mkdir -p work/flash
flashfile="work/flash/$(basename "$image" .syx)-${sha:0:12}.syx"
cp -p "$image" "$flashfile"
[[ "$(shasum -a 256 < "$flashfile" | cut -d' ' -f1)" == "$sha" ]] || die "copy of the image differs"

# 4. What the user runs (the hardware venv, requirements-hw.txt).
py=.venv/bin/python
[[ -x "$py" ]] || [[ ! -x .venv/Scripts/python.exe ]] || py=.venv/Scripts/python.exe  # Windows
[[ -x "$py" ]] || echo "build-image: note: no $py yet; set it up first (docs/SETUP.md, hardware venv)" >&2
stock="firmware/${source:-summit-firmware-2.2-build2121.syx}"
case "$source" in peak-*) product=Peak ;; *) product=Summit ;; esac
cat <<EOF

== Ready to flash
   image  $flashfile
   sha256 $sha  ($size bytes)
   from   $definition at $commit$dirty

The user runs every command below, one at a time, in their own terminal
(zsh or bash):

cd "$root"

Recovery, if the synth doesn't come back (docs/recovery.md):
  1. Power the $product off.
  2. Hold the three buttons left of the screen and power it on.
  3. It enumerates as "$product Bootloader". Re-flash stock (or use Components):

$py -I tools/flash.py flash $stock

The flash: check, dry run, then the real one. flash.py asks for the
confirmation: type flash.

$py -I tools/flash.py check $flashfile

$py -I tools/flash.py flash $flashfile --dry-run

$py -I tools/flash.py flash $flashfile --log work/flash-${sha:0:8}-\$(date +%F).log

Then add a row to docs/hardware-log.md: commit $commit, image \`${sha:0:8}…${sha: -8}\`.
EOF

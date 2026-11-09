#!/usr/bin/env bash
# Fetch Novation Summit (and, for reference, Peak) update images into `firmware/`.
#
# The images are proprietary Focusrite/Novation content. They are git-ignored and
# must never be committed or redistributed; this script is how a checkout gets
# its own copy. It uses the same public catalogue the Components updater reads:
# each file endpoint answers with a redirect to a pre-signed download and needs
# no account, cookies or connected instrument.
#
# Every image is checked against a pinned SHA-256, so a truncated or substituted
# download fails here instead of later in the tooling.
#
# Usage:
#   scripts/fetch-firmware.sh              # Summit firmware + FPGA (default set)
#   scripts/fetch-firmware.sh --all        # Summit and Peak images
#   scripts/fetch-firmware.sh --list       # print the Summit/Peak catalogue entries
#   FIRMWARE_DIR=/tmp/fw scripts/fetch-firmware.sh
#
# A newer release means adding a row to IMAGES below (id, name and hash).
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${FIRMWARE_DIR:-$repo_root/firmware}"
base="https://components.novationmusic.com/api/v2/firmwares"

# set   id   file name                             sha256
IMAGES="
summit 154 summit-firmware-2.2-build2121.syx  83b28931293647f2b4bfcf524c6875d3845468e6f0c037641c4318e3d249396f
summit 144 summit-fpga-2.1-build778.syx       57fed4dfc7c733c9f5bb6fca2f63aa8e85b3e11f55129028acad482cca9a0d3b
peak   155 peak-firmware-2.2-build2108.syx    f9d50b4268a5c612b71d4cafd45dc01a02ecdf0902aa6e31784ad4d1bc4de26e
peak   142 peak-fpga-2.1-build469.syx         317d48663036feb5bce51fc8c5448c618f0cf8673c4bef2e2a4b1631ad18924d
"

if [[ "${1:-}" == "--list" ]]; then
    curl -fsSL "$base" | python3 -I -c '
import json, sys
for f in json.load(sys.stdin)["firmwares"]:
    if f["product"].lower().startswith(("summit", "peak")):
        print("{:>4}  {:<7} {:<8}  v{:<6} build {}".format(
            f["id"], f["product"], f["firmware_type"], f["version"], f["build"]))
'
    exit 0
fi

sets="summit"
[[ "${1:-}" == "--all" ]] && sets="summit peak"

if command -v sha256sum >/dev/null; then
    sha256() { sha256sum "$1" | cut -d' ' -f1; }
else
    sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
fi
command -v curl >/dev/null || { echo "missing curl" >&2; exit 1; }

mkdir -p "$dest"

# fetch <id> <filename> <expected sha256>
fetch() {
    local id="$1" name="$2" want="$3"
    local path="$dest/$name" part="$dest/$name.part"

    if [[ -f "$path" ]] && [[ "$(sha256 "$path")" == "$want" ]]; then
        echo "ok      $name (already present)"
        return
    fi

    echo "fetch   $name (id $id)"
    # -f turns the 4xx/5xx returned for a retired build into an error instead
    # of saving an HTML body under a .syx name.
    if ! curl -fsSL --retry 3 -o "$part" "$base/$id/file"; then
        rm -f "$part"
        echo "download failed for $name" >&2
        exit 1
    fi
    local got
    got="$(sha256 "$part")"
    if [[ "$got" != "$want" ]]; then
        rm -f "$part"
        echo "checksum mismatch for $name" >&2
        echo "  expected $want" >&2
        echo "  got      $got" >&2
        exit 1
    fi
    mv "$part" "$path"
    echo "ok      $name ($(wc -c < "$path" | tr -d ' ') bytes)"
}

sums=""
while read -r set id name sha; do
    [[ -z "$set" ]] && continue
    [[ " $sets " == *" $set "* ]] || continue
    fetch "$id" "$name" "$sha"
    sums+="$sha  $name"$'\n'
done <<< "$IMAGES"

# Catalogue snapshot: documents which builds existed when the pins were chosen.
if curl -fsSL -o "$dest/catalog-snapshot.json.part" "$base"; then
    mv "$dest/catalog-snapshot.json.part" "$dest/catalog-snapshot.json"
    echo "ok      catalog-snapshot.json"
else
    echo "warn    catalogue unavailable; keeping any previous snapshot" >&2
    rm -f "$dest/catalog-snapshot.json.part"
fi

# Only the images verified in this run, relative to the firmware directory.
printf '%s' "$sums" > "$dest/SHA256SUMS"

echo
echo "wrote $dest/SHA256SUMS (re-check: cd \"$dest\" && shasum -a 256 -c SHA256SUMS)"
echo "These files are Focusrite/Novation property: keep them out of git."

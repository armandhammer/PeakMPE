#!/usr/bin/env bash
# Rebuild the patch in the dev image and require the committed descriptor's
# bytes (tools/web_descriptor.py compare), on each platform given, and require
# every platform to compile the same blob (docs/SETUP.md, "Reproducible
# patch bytes").
#
#   scripts/check-repro.sh                          this machine's platform
#   scripts/check-repro.sh linux/arm64 linux/amd64  both (one of them emulated)
#   BLOB_ONLY=1 scripts/check-repro.sh ...          without the firmware (CI)
#
# Without Novation's file in firmware/ only the compiled blob is compared;
# with it, the whole descriptor (hooks, header, output hashes) as well.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
descriptor="${DESCRIPTOR:-web/patches/mpe.json}"
extra=()
[[ -n "${BLOB_ONLY:-}" ]] && extra+=(--blob-only)
[[ $# -gt 0 ]] || set -- ""

status=0
blobs=()
for platform in "$@"; do
    label="${platform:-native}"
    echo "== $label"
    if out="$(DEV_PLATFORM="$platform" scripts/dev python -I tools/web_descriptor.py compare "$descriptor" ${extra[@]+"${extra[@]}"} 2>&1)"; then
        echo "$out"
        blobs+=("$(grep '^blob ' <<< "$out" || echo "no blob line")")
    else
        echo "$out"
        echo "== $label: FAILED" >&2
        status=1
    fi
done

if [[ $status == 0 && ${#blobs[@]} -gt 1 ]]; then
    for b in "${blobs[@]}"; do
        [[ "$b" == "${blobs[0]}" ]] || { echo "== the platforms compiled different blobs" >&2; status=1; }
    done
    [[ $status == 0 ]] && echo "== identical blob on: $*"
fi
[[ $status == 0 ]] && echo "== repro ok: $descriptor matches the source"
exit "$status"

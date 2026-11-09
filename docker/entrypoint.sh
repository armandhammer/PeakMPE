#!/usr/bin/env bash
# Entrypoint of the dev image (docker/Dockerfile), started by scripts/dev.
#
# scripts/dev starts the container as root with SUMMIT_MPE_UID/GID set to the
# host user. This gives the cache volumes to that user (a fresh named volume
# belongs to root), then runs the command as that user, so files written into
# the checkout and work/ belong to the host user, on Linux hosts too.
#
# Before an npm or npx command it runs `npm ci` in web/ if web/node_modules
# (a volume of its own, see scripts/dev) was installed from a different
# web/package-lock.json or Node version.
set -euo pipefail

uid="${SUMMIT_MPE_UID:-}"
gid="${SUMMIT_MPE_GID:-}"
if [[ "$(id -u)" == 0 && -n "$uid" && "$uid" != 0 ]]; then
    IFS=: read -r -a dirs <<< "${SUMMIT_MPE_OWN:-}"
    for d in "${dirs[@]}"; do
        [[ -n "$d" ]] || continue
        mkdir -p "$d"
        [[ "$(stat -c %u "$d")" == "$uid" ]] || chown "$uid:$gid" "$d"
    done
    exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$0" "$@"
fi

export HOME="${HOME_IN_IMAGE:-/cache/home}"
mkdir -p "$HOME" 2>/dev/null || true

if [[ $# -gt 0 && ( "$1" == npm || "$1" == npx ) && -n "${SUMMIT_MPE_WEB:-}" && -f "$SUMMIT_MPE_WEB/package-lock.json" ]]; then
    want="$(cat "$SUMMIT_MPE_WEB/package-lock.json" <(node --version) | sha256sum | cut -d' ' -f1)"
    stamp="$SUMMIT_MPE_WEB/node_modules/.summit-mpe-lock"
    if [[ "$(cat "$stamp" 2>/dev/null)" != "$want" ]]; then
        echo "dev: npm ci in web/ (package-lock.json or Node changed)" >&2
        # node_modules is a volume mount point: empty it rather than remove it.
        find "$SUMMIT_MPE_WEB/node_modules" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
        (cd "$SUMMIT_MPE_WEB" && npm ci --no-audit --no-fund --loglevel=error) >&2
        echo "$want" > "$stamp"
    fi
fi

[[ $# -gt 0 ]] || set -- bash
exec "$@"

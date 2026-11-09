#!/usr/bin/env bash
# Optional: point git at the repository's hooks in .githooks/, which refuse to
# commit or push firmware and generated files (CONTRIBUTING.md). CI runs the
# same file check on every pull request.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chmod +x "$repo_root"/.githooks/*
git -C "$repo_root" config core.hooksPath .githooks
echo "hooks installed: $(git -C "$repo_root" config core.hooksPath)"

#!/usr/bin/env bash
# Install the pinned Ghidra release and build its native components for this host.
#
#   scripts/install-ghidra.sh            # installs into ~/tools
#   GHIDRA_PREFIX=/opt/re scripts/install-ghidra.sh
#
# Official releases ship no macOS natives, so the decompiler is built locally
# with Ghidra's bundled Gradle wrapper (needs Xcode Command Line Tools and an
# internet connection). The zip is verified against the SHA-256 that GitHub
# publishes for the release asset.
set -euo pipefail

version="12.1.4"
stamp="20260921"
sha256="ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db"

prefix="${GHIDRA_PREFIX:-$HOME/tools}"
zip="ghidra_${version}_PUBLIC_${stamp}.zip"
url="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${version}_build/$zip"
install_dir="$prefix/ghidra_${version}_PUBLIC"

if [[ -z "${JAVA_HOME:-}" && -d /opt/homebrew/opt/openjdk@21 ]]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
fi
[[ -x "${JAVA_HOME:-}/bin/java" ]] || { echo "JDK 21 not found: brew bundle, or set JAVA_HOME" >&2; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Xcode Command Line Tools missing: xcode-select --install" >&2; exit 1; }

mkdir -p "$prefix/downloads"
if [[ ! -f "$prefix/downloads/$zip" ]]; then
    curl -fL --retry 3 -o "$prefix/downloads/$zip.part" "$url"
    mv "$prefix/downloads/$zip.part" "$prefix/downloads/$zip"
fi
echo "$sha256  $prefix/downloads/$zip" | shasum -a 256 -c -

if [[ ! -d "$install_dir" ]]; then
    unzip -q "$prefix/downloads/$zip" -d "$prefix"
fi

(cd "$install_dir/support/gradle" && ./gradlew buildNatives --console=plain -q)

echo
echo "Ghidra $version installed at $install_dir"
echo "export GHIDRA_INSTALL_DIR=\"$install_dir\""

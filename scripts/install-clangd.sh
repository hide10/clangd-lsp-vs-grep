#!/usr/bin/env bash
# Install a standalone clangd without sudo / apt.
# Drops the binary into ~/.local/bin/clangd (make sure that's on your PATH).
#
#   bash scripts/install-clangd.sh          # default version
#   CLANGD_VERSION=22.1.0 bash scripts/install-clangd.sh
set -euo pipefail

CLANGD_VERSION="${CLANGD_VERSION:-22.1.0}"
DEST="${CLANGD_DEST:-$HOME/.local/bin}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

url="https://github.com/clangd/clangd/releases/download/${CLANGD_VERSION}/clangd-linux-${CLANGD_VERSION}.zip"

echo "Downloading clangd ${CLANGD_VERSION} ..."
curl -fsSL -o "$TMP/clangd.zip" "$url"
unzip -q "$TMP/clangd.zip" -d "$TMP"

mkdir -p "$DEST"
ln -sf "$TMP/clangd_${CLANGD_VERSION}/bin/clangd" "$DEST/clangd" 2>/dev/null || true
# The symlink above points into a temp dir; copy the whole extracted tree to a stable spot instead.
STABLE="$HOME/.local/clangd_${CLANGD_VERSION}"
rm -rf "$STABLE"
mv "$TMP/clangd_${CLANGD_VERSION}" "$STABLE"
ln -sf "$STABLE/bin/clangd" "$DEST/clangd"

echo
"$DEST/clangd" --version
echo
echo "Installed to $DEST/clangd"
echo "If 'clangd' is not found, add this to your shell rc:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""

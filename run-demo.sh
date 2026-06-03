#!/usr/bin/env bash
# One command to reproduce the grep-vs-LSP comparison.
#   1. installs clangd into ~/.local/bin if it's missing
#   2. runs the probe against demo-project/
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v clangd >/dev/null 2>&1; then
    echo "clangd not found, installing a standalone copy..."
    bash scripts/install-clangd.sh
fi

python3 scripts/lsp_probe.py demo demo-project

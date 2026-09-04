#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
export PATH

if [ "$(uname -m)" != "arm64" ]; then
  echo "Fresnel v0.1 currently requires an Apple Silicon Mac." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it from https://brew.sh and rerun this script." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  brew install --yes uv
fi

if ! command -v glow >/dev/null 2>&1; then
  brew install --yes glow
fi

if ! command -v termtex >/dev/null 2>&1; then
  brew install --yes darkwebber/tap/termtex
fi

cd "$SCRIPT_DIR"
shasum -a 256 -c SHA256SUMS
uv tool install --force ./fresnel_agent-0.4.0-py3-none-any.whl

if ! command -v fresnel >/dev/null 2>&1; then
  echo "Fresnel was installed, but its bin directory is not on PATH." >&2
  echo "Add $HOME/.local/bin to PATH, then run: fresnel setup" >&2
  exit 1
fi

fresnel setup

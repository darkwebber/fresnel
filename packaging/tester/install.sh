#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
export PATH

if [ "$(uname -m)" != "arm64" ]; then
  echo "Fresnel currently requires an Apple Silicon Mac." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it from https://brew.sh and rerun this script." >&2
  exit 1
fi

if [ ! -x /opt/homebrew/opt/python@3.13/bin/python3.13 ]; then
  brew install --yes python@3.13
fi
PYTHON_BIN=/opt/homebrew/opt/python@3.13/bin/python3.13

if ! command -v glow >/dev/null 2>&1; then
  brew install --yes glow
fi

if ! command -v termtex >/dev/null 2>&1; then
  brew install --yes darkwebber/tap/termtex
fi

cd "$SCRIPT_DIR"
shasum -a 256 -c SHA256SUMS
RUNTIME_ROOT="$HOME/Library/Application Support/Fresnel/cli"
mkdir -p "$RUNTIME_ROOT" "$HOME/.local/bin"
"$PYTHON_BIN" -m venv "$RUNTIME_ROOT"
"$RUNTIME_ROOT/bin/python" -m pip install --disable-pip-version-check --no-compile \
  --force-reinstall ./fresnel_agent-0.5.0-py3-none-any.whl
ln -sf "$RUNTIME_ROOT/bin/fresnel" "$HOME/.local/bin/fresnel"
install -m 0755 ./fresnel-ui ./fresnel-supervisor "$HOME/.local/bin/"

if ! command -v fresnel >/dev/null 2>&1; then
  echo "Fresnel was installed, but its bin directory is not on PATH." >&2
  echo "Add $HOME/.local/bin to PATH, then run: fresnel setup" >&2
  exit 1
fi

fresnel setup

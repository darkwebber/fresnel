#!/bin/sh
set -eu

if [ "$(uname -m)" != "arm64" ]; then
  echo "Fresnel currently supports Apple Silicon Macs only." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Install Homebrew from https://brew.sh, then rerun this installer." >&2
    exit 1
  fi
  brew install uv
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
uv tool install --force "$PROJECT_DIR[setup]"
fresnel setup


#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /path/to/harness_eval" >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
SUITE_DIR=$1
RESULT_DIR="$PROJECT_DIR/benchmark-results"
mkdir -p "$RESULT_DIR"

failures=0
for task in chunked sessionize sql_dedup; do
  if ! fresnel run \
    --repo "$SUITE_DIR/$task" \
    --plan "$PROJECT_DIR/benchmarks/plans/$task.json" \
    --output "$RESULT_DIR/$task.json"; then
    failures=$((failures + 1))
  fi
done

exit "$failures"

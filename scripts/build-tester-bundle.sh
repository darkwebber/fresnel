#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
VERSION=0.2.0
STAGE="$PROJECT_DIR/dist/fresnel-$VERSION-macos-arm64"
ARCHIVE="$PROJECT_DIR/dist/fresnel-$VERSION-macos-arm64-tester.tar.gz"
ZIP_ARCHIVE="$PROJECT_DIR/dist/fresnel-$VERSION-macos-arm64-tester.zip"

rm -rf "$STAGE"
mkdir -p "$STAGE"
cp "$PROJECT_DIR/dist/fresnel_agent-$VERSION-py3-none-any.whl" "$STAGE/"
cp "$PROJECT_DIR/packaging/tester/install.sh" "$STAGE/"
cp "$PROJECT_DIR/packaging/tester/README.txt" "$STAGE/"
chmod +x "$STAGE/install.sh"

cd "$STAGE"
shasum -a 256 "fresnel_agent-$VERSION-py3-none-any.whl" > SHA256SUMS
cd "$PROJECT_DIR/dist"
tar -czf "$ARCHIVE" "fresnel-$VERSION-macos-arm64"
shasum -a 256 "$ARCHIVE" > "$ARCHIVE.sha256"
rm -f "$ZIP_ARCHIVE" "$ZIP_ARCHIVE.sha256"
ditto -c -k --sequesterRsrc --keepParent "fresnel-$VERSION-macos-arm64" "$ZIP_ARCHIVE"
shasum -a 256 "$ZIP_ARCHIVE" > "$ZIP_ARCHIVE.sha256"

echo "$ARCHIVE"
echo "$ZIP_ARCHIVE"

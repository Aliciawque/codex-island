#!/bin/bash
# Downloads and unpacks the Sparkle framework + tools into Vendor/Sparkle.
# Reuses only an extraction that completed for the requested version.

set -euo pipefail
cd "$(dirname "$0")/.."

SPARKLE_VERSION="2.9.1"
DEST="Vendor/Sparkle"

if [[ -f "${DEST}/.version" ]] &&
   [[ "$(cat "${DEST}/.version")" == "$SPARKLE_VERSION" ]] &&
   [[ -f "${DEST}/Sparkle.framework/Sparkle" && -x "${DEST}/bin/sign_update" ]]; then
  echo "Sparkle ${SPARKLE_VERSION} already vendored at ${DEST}"
  exit 0
fi

mkdir -p "$(dirname "$DEST")"
# Keep a failed download or extraction out of the reusable cache.
STAGING=$(mktemp -d "${DEST}.tmp.XXXXXX")
trap 'rm -rf "$STAGING"' EXIT
TARBALL="$STAGING/Sparkle.tar.xz"

echo "downloading Sparkle ${SPARKLE_VERSION}..."
curl -fsSL -o "$TARBALL" \
  "https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/Sparkle-${SPARKLE_VERSION}.tar.xz"

tar -xJf "$TARBALL" -C "$STAGING"
rm "$TARBALL"

if [[ ! -f "$STAGING/Sparkle.framework/Sparkle" || ! -x "$STAGING/bin/sign_update" ]]; then
  echo "error: Sparkle archive is missing its framework or signing tool" >&2
  exit 1
fi
printf '%s\n' "$SPARKLE_VERSION" > "$STAGING/.version"
rm -rf "$DEST"
mv "$STAGING" "$DEST"

echo "vendored Sparkle ${SPARKLE_VERSION} at ${DEST}"

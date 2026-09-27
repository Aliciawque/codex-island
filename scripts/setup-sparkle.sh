#!/bin/bash
# Downloads and unpacks the Sparkle framework + tools into Vendor/Sparkle.
# Reuses only an extraction that completed for the requested version.

set -euo pipefail
cd "$(dirname "$0")/.."

SPARKLE_VERSION="2.9.1"
DEST="Vendor/Sparkle"
LOCK_DIR="${DEST}.lock"
MAX_ATTEMPTS=3
STAGING=""
LOCK_HELD=""

cleanup() {
  if [[ -n "$STAGING" ]]; then
    rm -rf "$STAGING"
  fi
  if [[ -n "$LOCK_HELD" ]]; then
    rm -rf "$LOCK_DIR"
  fi
}
trap cleanup EXIT

mkdir -p "$(dirname "$DEST")"

# Serialize concurrent runs. A run killed mid-flight leaves the lock behind,
# but then its pid is gone too, so a stale lock is safe to drop.
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  if [[ -f "$LOCK_DIR/pid" ]] && ! kill -0 "$(cat "$LOCK_DIR/pid")" 2>/dev/null; then
    rm -rf "$LOCK_DIR"
  else
    sleep 0.2
  fi
done
LOCK_HELD=1
echo "$$" > "$LOCK_DIR/pid"

# A run killed mid-publish can leave a backup behind; nothing else can be
# mid-publish while we hold the lock, so anything matching is stale.
for leftover in "${DEST}".bak.*; do
  [[ -e "$leftover" ]] && rm -rf "$leftover"
done

framework_ok() {
  [[ -f "${DEST}/Sparkle.framework/Sparkle" && -x "${DEST}/bin/sign_update" ]]
}

if framework_ok; then
  if [[ -f "${DEST}/.version" ]] && [[ "$(cat "${DEST}/.version")" == "$SPARKLE_VERSION" ]]; then
    echo "Sparkle ${SPARKLE_VERSION} already vendored at ${DEST}"
  else
    # Verified legacy cache: stamp the marker instead of re-downloading, so
    # offline builds keep working.
    printf '%s\n' "$SPARKLE_VERSION" > "${DEST}/.version"
    echo "adopted existing Sparkle cache at ${DEST}"
  fi
  exit 0
fi

# A transient network failure should not fail the build outright: retry the
# download/extraction with backoff inside a single run. A failed attempt
# never touches the reusable cache.
attempt=1
while (( attempt <= MAX_ATTEMPTS )); do
  if [[ -n "$STAGING" ]]; then
    rm -rf "$STAGING"
  fi
  STAGING=$(mktemp -d "${DEST}.tmp.XXXXXX")
  TARBALL="$STAGING/Sparkle.tar.xz"
  echo "downloading Sparkle ${SPARKLE_VERSION} (attempt ${attempt}/${MAX_ATTEMPTS})..."
  if curl -fsSL -o "$TARBALL" \
      "https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/Sparkle-${SPARKLE_VERSION}.tar.xz" \
    && tar -xJf "$TARBALL" -C "$STAGING" \
    && [[ -f "$STAGING/Sparkle.framework/Sparkle" && -x "$STAGING/bin/sign_update" ]]; then
    break
  fi
  echo "warning: download/extraction failed (attempt ${attempt}/${MAX_ATTEMPTS})" >&2
  sleep $(( 1 << (attempt - 1) ))
  attempt=$(( attempt + 1 ))
done
if (( attempt > MAX_ATTEMPTS )); then
  echo "error: failed to download and extract Sparkle ${SPARKLE_VERSION} after ${MAX_ATTEMPTS} attempts" >&2
  exit 1
fi
rm -f "$TARBALL"
printf '%s\n' "$SPARKLE_VERSION" > "$STAGING/.version"

# Move any existing cache aside, then rename the staged dir into place. The
# lock above keeps concurrent runs from interleaving here.
BACKUP="${DEST}.bak.$$"
if [[ -e "$DEST" ]]; then
  mv "$DEST" "$BACKUP"
fi
mv "$STAGING" "$DEST"
STAGING=""
rm -rf "$BACKUP"

echo "vendored Sparkle ${SPARKLE_VERSION} at ${DEST}"

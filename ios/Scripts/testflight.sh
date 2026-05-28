#!/usr/bin/env bash
# Build + upload a WHV iOS build to TestFlight (App Store Connect).
#
# One-time prereqs:
#   - The app record for `com.wagner-hausverwaltung.portal` exists in
#     App Store Connect.
#   - An App Store Connect API key (Users and Access → Integrations →
#     App Store Connect API, role: App Manager). Save the .p8 either at
#     ~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8 (auto-discovered)
#     or anywhere and point ASC_KEY_PATH at it.
#   - The "Apple Distribution: … (K4KDX9GN74)" cert in the login keychain
#     (already present on Luis's Mac).
#
# Usage:
#   ASC_KEY_ID=XXXXXXXXXX \
#   ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
#   [ASC_KEY_PATH=/abs/path/AuthKey_XXXXXXXXXX.p8] \
#     ios/Scripts/testflight.sh
#
# Each run stamps a fresh build number (UTC timestamp) into
# CURRENT_PROJECT_VERSION → CFBundleVersion, so App Store Connect never
# rejects a duplicate. The user-facing version (MARKETING_VERSION) stays
# as set in the project — bump it by hand for a new public version.
set -euo pipefail

cd "$(dirname "$0")/.."  # → ios/

PROJECT="WHV.xcodeproj"
SCHEME="WHV"
BUILD_DIR="build"
ARCHIVE="$BUILD_DIR/WHV.xcarchive"
EXPORT_OPTS="ExportOptions.plist"
BUILD_NUMBER="$(date -u +%Y%m%d%H%M)"

: "${ASC_KEY_ID:?set ASC_KEY_ID (App Store Connect API key id)}"
: "${ASC_ISSUER_ID:?set ASC_ISSUER_ID (App Store Connect issuer id)}"

AUTH_ARGS=(-authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
if [[ -n "${ASC_KEY_PATH:-}" ]]; then
  AUTH_ARGS+=(-authenticationKeyPath "$ASC_KEY_PATH")
fi

echo "▸ Archiving $SCHEME (build $BUILD_NUMBER)…"
rm -rf "$ARCHIVE"
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration Release \
  -destination "generic/platform=iOS" \
  -archivePath "$ARCHIVE" \
  CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  -allowProvisioningUpdates "${AUTH_ARGS[@]}" \
  clean archive

echo "▸ Exporting + uploading to App Store Connect…"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$EXPORT_OPTS" \
  -exportPath "$BUILD_DIR/export" \
  -allowProvisioningUpdates "${AUTH_ARGS[@]}"

echo "✓ Uploaded build $BUILD_NUMBER — it appears in TestFlight once ASC finishes processing (a few minutes)."

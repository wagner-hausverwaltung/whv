# iOS → TestFlight

How to ship a WHV iOS build to TestFlight. Two paths: a one-command
script (preferred, repeatable) and the Xcode GUI fallback.

## Prerequisites (one-time)

1. **App record in App Store Connect** for bundle id
   `com.wagner-hausverwaltung.portal` (and the embedded widget
   `com.wagner-hausverwaltung.portal.WHVWidgets` is covered by the same
   app). Create it under *Apps → +* if it doesn't exist yet.
2. **Distribution certificate** — `Apple Distribution: Luis Wagner
   (K4KDX9GN74)` in the login keychain. Already present on Luis's Mac.
3. **App Store Connect API key** — *Users and Access → Integrations →
   App Store Connect API → +*, role **App Manager**. Download the
   `AuthKey_<KEYID>.p8` (one-time download) and note the **Key ID** and
   the team's **Issuer ID**. Save the file at
   `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8` so `xcodebuild`
   finds it automatically.

> Signing note: the app + widget targets are on team **K4KDX9GN74**
> (matches the dist cert). The `WHVUITests` target is on a different team
> (`5XQDFG9H83`) but is **not** part of the archive, so it doesn't affect
> the upload. Fix it before running UI tests, not before shipping.

## Preferred: the script

```sh
ASC_KEY_ID=XXXXXXXXXX \
ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
ios/Scripts/testflight.sh
```

(Add `ASC_KEY_PATH=/abs/AuthKey_XXXX.p8` if the key isn't in the default
`~/.appstoreconnect/private_keys/` location.)

What it does:
- Archives the `WHV` scheme (Release), stamping `CURRENT_PROJECT_VERSION`
  with a fresh UTC timestamp → unique `CFBundleVersion` every run, so ASC
  never rejects a duplicate build number.
- `xcodebuild -exportArchive` with `ExportOptions.plist`
  (`destination: upload`) signs via the API key and uploads straight to
  TestFlight.
- The build appears under TestFlight after ASC finishes processing
  (usually a few minutes); add testers / fill export-compliance there.

The **marketing version** (`MARKETING_VERSION`, currently `0.1.0`) is
*not* auto-bumped — change it in the project for a new public version.

## Fallback: Xcode GUI

Open `ios/WHV.xcodeproj` → select **Any iOS Device** → **Product ▸
Archive** → in the Organizer pick the archive → **Distribute App ▸ App
Store Connect ▸ Upload**. Uses the signed-in Apple ID for signing +
upload; no API key needed.

## Future: CI

Once the API key lives in GitHub Actions secrets, this script drops into
a macOS-runner workflow (import the cert into a temp keychain, then run
`ios/Scripts/testflight.sh`). Not wired yet — deliberately kept as a
local script until a key is provisioned.

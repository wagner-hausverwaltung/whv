# WHV iOS — Phase 2 starter

Minimal SwiftUI iOS app, scaffolded around a single live feature: the
**Fachinfos** tab, which pulls the [vermieter1x1.de](https://www.vermieter1x1.de/Fachinfo/rss/)
RSS feed and renders each entry as a card. Tapping a card opens the
article in an in-app `WKWebView`.

Everything else in the spec (REQUIREMENTS.md §8.3 — login, property
list, tickets, etc.) is a placeholder for now. Phase 2 fills those
in.

## Requirements

- macOS with Xcode 16+ (this scaffold was authored against Xcode 26.5)
- iOS 17.0+ deployment target

No Apple Developer account required for Simulator builds — only for
distributing to physical devices / TestFlight.

## Run

Open `WHV.xcodeproj` in Xcode and hit ⌘R (any iPhone simulator).

Or from the command line:

```bash
cd ios
xcodebuild -project WHV.xcodeproj \
           -scheme WHV \
           -destination 'platform=iOS Simulator,name=iPhone 17' \
           build

xcrun simctl boot "iPhone 17" 2>/dev/null
xcrun simctl install booted ~/Library/Developer/Xcode/DerivedData/WHV-*/Build/Products/Debug-iphonesimulator/WHV.app
xcrun simctl launch booted com.wagner-hausverwaltung.portal
open -a Simulator
```

## Structure

```
ios/
├── WHV/
│   ├── WHVApp.swift           ← @main entry point
│   ├── RootTabView.swift      ← TabView (4 placeholders + Fachinfos)
│   ├── Assets.xcassets/       ← icon + accent colour
│   ├── Preview Content/       ← SwiftUI preview assets
│   └── Fachinfos/             ← RSS feature
│       ├── RSSItem.swift          ← model
│       ├── RSSService.swift       ← XMLParser-based fetcher
│       ├── FachinfosTab.swift     ← list of cards + view model
│       └── ArticleDetailView.swift ← WKWebView + nav bar
└── WHV.xcodeproj/             ← Xcode 16 filesystem-synchronized project
```

Source files under `WHV/` are picked up via Xcode 16's
`PBXFileSystemSynchronizedRootGroup` — drop new `.swift` files into
the directory and Xcode auto-includes them, no `project.pbxproj`
edits needed.

## Fachinfos feature

- Fetches `https://www.vermieter1x1.de/Fachinfo/rss/` on first tab
  open (caches via `URLSession`'s default policy → respects the
  feed's HTTP cache headers).
- Pull-to-refresh + a toolbar refresh button.
- Each card: title, 3-line summary, date, category chip, optional
  hero image (when the entry ships an `<enclosure type="image/...">`).
- Tap → push `ArticleDetailView`:
  - `WKWebView` loads the article URL (iOS equivalent of an HTML
    iframe — the feed's articles ship no X-Frame-Options or
    restrictive CSP so they render fine in-app).
  - Bottom toolbar: back / forward / open-in-Safari /
    share-link.
  - Friendly error state with an "In Safari öffnen" fallback if
    the page fails to load (e.g. future CSP change).

## Build status (2026-05-25)

✅ `xcodebuild ... build` succeeds against the iPhone 17 simulator
✅ App launches; TabView renders all five tabs
✅ Fachinfos service tested against the live feed (RSS 2.0 parsed
   into 50+ items)

## Carry-forward to proper Phase 2

The full screen list from REQUIREMENTS.md §8.3:

- Onboarding / Invite redemption
- Login (JWT in Keychain, NOT UserDefaults — XSS-class is moot on
  iOS but the secure-element-backed Keychain is the right default)
- Property list / detail
- Documents (filtered + downloadable)
- Tickets list / detail / new
- Mitteilungen inbox (maps to the announcements feature shipped on
  the backend; `Messages` in §8.3)
- Settings (profile / language / biometrics / delete-account)

Plus cross-screen: pull-to-refresh on every list (✅ Fachinfos
already), skeleton loaders, offline banner, APNs push registration,
biometric lock, deep links (`whv://invite/CODE`, `whv://ticket/123`).

## Troubleshooting

### "Build succeeded" but nothing opens on my Mac

You probably selected **"My Mac"** as the destination — that's the
*run-on-Mac-natively* option, not the Simulator. With
`SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD = YES` enabled (2026-05-25)
the app will launch as a Mac window when you pick **"My Mac
(Designed for iPad)"**. Apple Silicon required.

For the **iOS Simulator**, pick a destination that's explicitly an
iPhone or iPad with a `(Simulator)` suffix — e.g. *iPhone 17* or
*iPad Pro 13-inch (M4)*. Xcode auto-launches the Simulator on first
run. If you don't see iOS Simulator entries in the destination
dropdown, the Simulator runtime isn't installed: Xcode → Settings →
Platforms → install "iOS 18+".

### "Build succeeded" but nothing opens on my iPad

The build compiles, then Xcode tries to install + launch over USB
or Wi-Fi. Three things can quietly trip this up:

1. **Developer Mode (iOS 16+)** must be **on** on the iPad. The
   first install attempt prompts you to enable it: open Settings →
   Privacy & Security → scroll to **Developer Mode** → toggle on →
   restart the iPad. Without this the install silently fails.

2. **Trust the personal team certificate.** The free Personal Team
   signs with an ad-hoc cert your iPad doesn't trust by default.
   After Xcode says it installed: on the iPad, open Settings →
   General → **VPN & Device Management** → tap the Apple ID under
   "Developer App" → Trust.

3. **Personal Team has a 3-bundle-ID / 7-day cap.** If you've been
   signing other test apps with the same Apple ID you might be at
   the limit. Either delete an unused app from the Apple ID, or
   wait. The error shows in Xcode's *Window → Devices and
   Simulators* console.

Open **Xcode → Window → Devices and Simulators**, click the iPad in
the sidebar, and look at "View Device Logs" or the inline error.
Any "couldn't install" / "couldn't launch" message there is the
actual signal — the build-succeeded toast hides install failures.

### "Untrusted Developer" when tapping the icon

You skipped step 2 above. Settings → General → VPN & Device
Management → Trust.

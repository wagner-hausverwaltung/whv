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
xcrun simctl launch booted com.wagner-hausverwaltung.WHV
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

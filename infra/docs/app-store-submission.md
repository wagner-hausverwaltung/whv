# App Store submission runbook — WHV iOS

Single source-of-truth checklist tracking what's done, what's
blocking, and the order to do the rest in.

## Status snapshot (2026-05-28)

| Block | Status |
|---|---|
| iOS code | ✅ ready (clean audit — see §3) |
| Privacy manifest | ✅ `ios/WHV/PrivacyInfo.xcprivacy` written |
| Datenschutz draft | ✅ `infra/docs/datenschutz-app.md` — needs legal review + hosting |
| Developer Portal | ⏳ pending Luis |
| App Store Connect app record | ⏳ pending Luis |
| Marketing assets | ⏳ pending (icon ready, screenshots todo) |
| TestFlight | ⏳ blocked on portal setup |

## 1. Code-side artifacts (DONE)

### `PrivacyInfo.xcprivacy`

Declares:
- `NSPrivacyTracking = false` (we do not track)
- `NSPrivacyCollectedDataTypes`: Email, OtherUserContent, UserID — all
  linked-to-user, App Functionality, not tracking
- `NSPrivacyAccessedAPITypes`: UserDefaults with reason `CA92.1`
  (same-app + app-group)

Must stay in sync with App Store Connect → App Privacy questionnaire.

### Datenschutz draft

`infra/docs/datenschutz-app.md`. Needs:
1. Anwaltliche Prüfung
2. `{{TODO_DATUM_VOR_VERÖFFENTLICHUNG}}` befüllen
3. Hosten unter <https://wagner-hausverwaltung.com/datenschutz-app>
   oder als eigenständige Seite — URL ist in App Store Connect
   Pflichtfeld

## 2. Developer Portal setup (Luis, ~1 hr)

In `developer.apple.com → Certificates, Identifiers & Profiles`:

1. **App ID** `com.wagner-hausverwaltung.portal` — Explicit. Capabilities:
   - ✅ App Groups (use `group.com.wagner-hausverwaltung.portal`)
   - ✅ Time Sensitive Notifications (Live Activities)
   - ✅ Sign in with Apple — leave OFF (we don't use OAuth so it's
     not required by guideline 4.8)
   - ❌ Push Notifications — leave OFF (defer to task #72)
2. **App ID** `com.wagner-hausverwaltung.portal.WHVWidgets` —
   Explicit. Same App Group capability.
3. **Identifier → App Groups** → `group.com.wagner-hausverwaltung.portal`

> **Why everything ends in `.portal`.** The legacy `com.wagner-hausverwaltung.WHV`
> namespace was already claimed on Apple's side — both the app
> bundle ID and the matching App Group identifier. Probably an
> earlier personal-account prototype that never got cleaned up. We
> renamed both to `…portal` to match. No data loss on dev installs
> since we hadn't shipped yet; future installs see a fresh App
> Group container.
4. **Certificates → Apple Distribution** (one for the org)
5. **Profiles → App Store** for both bundle IDs, tied to the cert
6. In Xcode: Settings → Accounts → add the dev team. Both targets
   should auto-pick the new profiles.

## 3. App Store Connect setup (Luis, ~1 hr)

`appstoreconnect.apple.com → My Apps → New App`:

- **Name**: "Wagner Hausverwaltung"
- **Primary language**: Deutsch
- **Bundle ID**: pick the one from step 1
- **SKU**: `whv-portal-001`
- **User access**: Full Access

Once the app record exists, fill:

### App Information
- **Subtitle**: "Eigentümer- und Mieter-Portal" (max 30 chars)
- **Category**: Business (primary), Lifestyle (secondary)
- **Content Rights**: "Does not contain, show, or access third-party
  content" — true
- **Age Rating**: tap through the questionnaire → expect 4+

### App Privacy (CRITICAL — must match `PrivacyInfo.xcprivacy`)
- Data Collection: YES
- For each entry in the privacy manifest, add the matching answer:
  - **Contact Info → Email Address**: linked, used for App
    Functionality, not used for tracking
  - **User Content → Other User Content**: linked, App
    Functionality, not tracking (tickets / comments / Q&A)
  - **Identifiers → User ID**: linked, App Functionality, not
    tracking (our own UUID7, NOT the IDFA)
- Tracking: NO
- Privacy Policy URL: the hosted Datenschutz URL

### Pricing & Availability
- Free
- Available in: Germany (primary). Add Austria + Switzerland as
  bonus reach if Wagner serves those.

### App Review Information
- **Sign-in required**: YES
- **Demo Account**:
  - Sign-in method: "Demo button on login screen — no credentials
    needed. Tap the 'Demo' button below the login form to enter the
    app with seeded sample data."
  - Username/Password: leave blank, paste the above into Notes
- **Contact**: Luis's email + phone
- **Notes**: "App requires invitation by a property manager
  (Verwalter) for production accounts; reviewers should use Demo
  Mode for full app access. Demo mode is gated client-side and never
  hits real backend data."

### Export Compliance
- "Uses encryption" → YES (HTTPS)
- "Uses only exempt encryption" → YES (standard TLS, no custom
  cryptography) → exempt from US export filing.

## 4. Marketing assets

### App Icon — 1024×1024 PNG
- No transparency, no rounded corners
- Source: the existing Wagner Hausverwaltung logo. The dark-mode
  variant we already ship for the in-app header is fine; the icon
  field doesn't honor dark-mode at the App Store level so pick the
  light-bg variant.

### Screenshots — required sizes
| Device | Resolution | Required |
|---|---|---|
| 13" iPad Pro M4 | 2064 × 2752 | ✅ (we ship iPad) |
| 12.9" iPad Pro 6th gen | 2048 × 2732 | optional fallback |
| 6.9" iPhone 16 Pro Max | 1320 × 2868 | ✅ once iPhone-tested |
| 6.5" iPhone 11 Pro Max | 1242 × 2688 | optional fallback |

Recommended 5-6 screens:
1. Login + Demo button (anchor screen)
2. Active Liegenschaft + Schnellzugriff
3. ETV-Detail with Tagesordnung + Anhänge
4. Ticket-Detail mit Antwort-Thread
5. Dienstleister-Karte mit Kontaktoptionen
6. Property detail with Einheiten + Verträge

XCUITest scripting (task #99) will let you regen these reproducibly.

### Description (Deutsch)

Suggested copy (180–4000 chars):
```
Mit der Wagner Hausverwaltung App haben Sie Ihre Liegenschaft
immer dabei.

EIGENTÜMER & MIETER
• Aktuelle Mitteilungen, Versammlungstermine und Beschlüsse
• Termin-Live-Aktivität auf dem Sperrbildschirm vor der ETV
• Q&A unter Versammlungsprotokollen
• Anliegen melden – mit Bildanhang und Fortschritts-Tracking
• Direktwahl zum Verwalter aus jeder Ansicht

BEIRAT & VERWALTER
• Tickets, Mitteilungen und ETVs liegenschaftsübergreifend einsehbar
• Property-Filter für die Verwaltungsperspektive

SICHERHEIT
• Face-ID / Touch-ID App-Sperre
• Token nur lokal auf dem Gerät (kein iCloud-Sync)
• DSGVO-konform — Datenexport und Konto-Löschung jederzeit

Die App ist Teil des Wagner-Hausverwaltung-Portals. Ein Konto
erhalten Sie als bestehender Eigentümer oder Mieter automatisch
per Einladung; tippen Sie zum Anschauen "Demo" auf dem
Anmeldebildschirm.
```

### Keywords (max 100 chars, comma-sep, no spaces after comma)
```
hausverwaltung,WEG,eigentümer,mieter,beirat,liegenschaft,etv,
beschluss,protokoll,wagner
```

### What's New (für Folge-Updates)
Empty on the first submission — Apple shows the version note only
on updates.

## 5. Build + upload

```
# In Xcode:
1. Select WHV scheme + "Any iOS Device (arm64)" destination
2. Product → Archive
3. Wait. Organizer opens.
4. Distribute App → App Store Connect → Upload
5. ASC needs ~15–30 min to process
```

Then in App Store Connect:
- Activity → Builds — pick the new build for the version
- Submit for App Review → answer the final prompts → Done

## 6. TestFlight rollout

1. **Internal Testing** (no review needed, instant):
   - Add Luis + Dirk + me as App Store Connect users in the WHV team
   - Push build to internal group
2. **External Testing** (Beta App Review required, ~24h):
   - Create group "Beirat" or similar
   - Add 2–3 trusted Eigentümer by email
   - Submit the build for Beta App Review (separate from final
     App Store Review — usually faster + lighter)

## 7. Common rejection triggers — pre-empted

Audit pass (2026-05-28) confirms WHV is clean on every one of these:

| Guideline | Risk | Mitigation |
|---|---|---|
| 2.1 App Completeness — "we couldn't sign in" | Reviewers blocked on invite-only flow | ✅ Demo button, no creds needed |
| 5.1.1(v) Account deletion | Required since June 2022 | ✅ Einstellungen → Konto löschen → DELETE /me |
| 5.1.2 Privacy policy URL | Required for any login | ⏳ hosted at TBD |
| 5.1.1 Data nutrition labels mismatch | Sentry / Analytics differs from manifest | ✅ No Sentry / Analytics shipped in iOS |
| 4.2.2 Web wrapper | Apps that are just wrappers around websites | ✅ Native SwiftUI throughout — Widgets, Live Activity |
| 4.8 Sign-in with Apple required | Triggered only if other social login | ✅ N/A — invite + email/password, no OAuth |
| 5.5 Mobile Web Sign-in | n/a | ✅ |
| 2.5.1 Public APIs | Underscore SPI usage | ✅ Audit clean |
| Privacy manifest missing | Auto-reject since May 2024 | ✅ Written |
| Missing permission strings | Crashes prompting Face ID etc. | ✅ NSFaceIDUsageDescription present |
| Demo creds in production binary | Reviewer-visible secret | ✅ All gated by `DemoFlag.isActive`, no production tokens |

## 8. Open questions for Luis

* **Privacy policy host** — where do you want to publish the
  `datenschutz-app.md`? Suggest a Bluehost path on
  `wagner-hausverwaltung.com/datenschutz-app` since that domain is
  already handed over.
* **Support email** — `support@wagner-hausverwaltung.com` or your
  personal address as the contact during review?
* **Marketing copy** — happy with the German description draft
  above, or want me to do a second pass?

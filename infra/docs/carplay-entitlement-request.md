# CarPlay Entitlement — Antrag (Driving Task)

Stand 2026-08-21. Der Antrag muss vom Apple-Developer-Account-Inhaber eingereicht
werden; dieses Dokument liefert den fertigen Text und die Eckdaten.

## Wo einreichen

<https://developer.apple.com/contact/carplay/> — eingeloggt als Account Holder
(Team **K4KDX9GN74**). Das Formular: App-Typ, CarPlay Entitlement Addendum (Terms) und —
unterhalb — drei Freitextfelder (App-Beschreibung, geplante CarPlay-Features, App-Store-URL).

Bearbeitung dauert erfahrungsgemäß **2–6 Wochen**; Rückfragen kommen per Mail. Nach
Freigabe erscheint das Entitlement `com.apple.developer.carplay-driving-task` unter
Certificates → Identifiers → App ID → Additional Capabilities und muss ins
Provisioning Profile + in `ios/WHV/WHV.entitlements`.

## Eckdaten für das Formular

| Feld | Wert |
|---|---|
| App name | WHV — Wagner Hausverwaltung |
| Bundle ID | `com.wagner-hausverwaltung.portal` |
| Team ID | K4KDX9GN74 |
| App Store status | live (1.3.x) |
| Category requested | **Driving Task** |
| Templates we will use | Grid, List, Information, Alert |
| Company | Wagner Hausverwaltung GmbH, Staufeneckstraße 17, 70469 Stuttgart |

## Erteilt (2026-08-23)

Apple: „The entitlement for CarPlay Driving Task App has been assigned to your
account." Seitdem trägt `ios/WHV/WHV.entitlements` den Key
`com.apple.developer.carplay-driving-task` für ALLE Konfigurationen; die
Simulator-only-Datei `WHV.debug.entitlements` und die SDK-Bedingung im
Projekt sind entfernt. Die Managed Capability muss am App-ID
`com.wagner-hausverwaltung.portal` aktiv sein (Developer-Portal → Identifiers →
Additional Capabilities → CarPlay Driving Task); automatisches Signieren zieht
sie dann ins Profil. Review Notes (§4) bei der nächsten App-Store-Einreichung
nicht vergessen — Text unten.

## Eingereicht — Case-ID 21774792 (2026-08-21)

Apples Eingangsbestätigung listet drei Felder, die **leer** übermittelt wurden:
„Tell us about your app", „What specific CarPlay features do you plan to implement?",
„App Store URL (optional)". Das Formular hatte sie also doch (offenbar unterhalb der
Terms). Apple bewertet genau danach — deshalb **per E-Mail nachreichen**: Antwort auf
die Bestätigungsmail mit der Zeile `Case-ID: 21774792` und dem Text unten plus
App-Store-URL. Derselbe Text gehört später in die Review Notes in App Store Connect
(Addendum §4 verlangt die schriftliche Offenlegung der CarPlay-Nutzung).

## Drei Stellen im Addendum, die unser Design bestimmen

- **§3.1:** Mehrere Kategorien je App sind möglich („primarily designed to provide a
  combination") → Voice-Based Conversational kann später zusätzlich beantragt werden.
- **§3.10:** Driving-Task-Apps dürfen *nicht* „primarily designed to provide a list of
  POIs or locations" sein und keine fahrfremde Funktion zeigen (Account, Settings),
  keine Medien. → **Fahrt ist das Zentrum**; Objekte erscheinen nur als „Ziel wählen"
  innerhalb der Fahrt, Kontakte als „am Ziel anrufen", Heute als „nächstes Ziel" —
  kein eigenständiges Objekt-/Kontaktverzeichnis im Auto.
- **§4:** Datenschutz (GPS-Tracking) liegt vollständig bei uns → Einwilligung des
  Fahrers vor dem ersten Tracking, nur Dienstfahrten speichern.

## Antragstext — per Mail an die Case-ID nachreichen, später Review Notes (§4)

> WHV is the field-service app of Wagner Hausverwaltung GmbH, a German property
> management company. Our property managers spend a large part of their day
> driving between the residential properties we manage (site inspections,
> owners' meetings, contractor appointments). The CarPlay extension supports
> exactly that driving task and nothing else:
>
> 1. **Mileage log (Fahrtenbuch).** A trip starts automatically when the
>    phone connects to CarPlay and ends when it disconnects. On arrival the
>    driver confirms the destination property (pre-selected from GPS) and the
>    trip purpose with a single tap. Trips are reimbursed per kilometre and
>    billed as travel expenses to the respective property, so accurate,
>    low-friction logging while driving is the core use case.
> 2. **Destination selection.** A list of managed properties, ordered by how
>    often they are visited, each with a one-tap hand-off to Apple Maps for
>    turn-by-turn navigation.
> 3. **Contact at the destination.** For the selected property, the on-site
>    contacts (owners, caretaker, contractors) with one-tap phone call and a
>    one-tap "I'm running late" notice that our backend delivers by e-mail —
>    no typing, no messaging UI in the car.
> 4. **Today.** A short read-only list of the driver's appointments and open
>    tasks for the day, so the next destination can be picked without
>    touching the phone.
>
> The CarPlay UI uses only the Grid, List, Information and Alert templates.
> There is no free-form content, no document viewing, no text entry and no
> media. Everything beyond a glance-and-tap interaction (ticket details,
> documents, forms) stays on the phone and is not reachable from CarPlay.
>
> Target users are our own employees (currently two property managers); the
> app is distributed on the App Store because owners and tenants use the same
> app for their portal. The CarPlay scene is only available to users with
> the property-manager role.

## Review Notes für App Store Connect (ab Build 1.3.8 (72), 2026-08-28)

Einfügen unter „App Review Information → Notes"; der Antragstext oben bleibt der
Kern, ergänzt um Demo-Zugang und die neuen Systemintegrationen.

> **Demo access (no credentials needed):** on the login screen tap "View demo"
> → "Verwalter (mileage log, CarPlay, Siri)". This signs in as a property
> manager with sample data (5 sample properties in Stuttgart, contacts,
> appointments, sample trips). Nothing is sent to our servers in demo mode.
> "Eigentümer / Beirat" shows the owner/board-member portal (tickets,
> documents, meetings, meters).
>
> **CarPlay (Driving Task entitlement, granted 2026-08-23, Case-ID 21774792):**
> the demo manager role also enables the CarPlay scene. In the Simulator:
> I/O → External Displays → CarPlay. Root grid: Trip (start/end, purpose
> picked from a list), Destination (managed properties by proximity → Apple
> Maps hand-off), Site visits (sales inquiries with an address), Today
> (appointments/open tasks, read-only), Call at destination. Only Grid, List,
> Information and Alert templates; no free text, no documents, no media.
>
> **Location / Motion:** "Always" location + CoreMotion are used solely for the
> mileage log of the manager role (trip auto-start when driving, arrival
> detection via a 100 m geofence around the destination property). Owners and
> tenants are never asked for location. The manager consents explicitly in
> Settings before any tracking starts.
>
> **CallKit Call Directory extension:** identifies incoming calls from the
> company's own owner/tenant/contractor contacts ("Name · Property · Role").
> Identification only — no call blocking. The list is downloaded from our
> backend for the signed-in manager; it is empty in demo mode.
>
> **Siri / App Intents** (German and English phrases): "Ask WHV" / "Frag WHV"
> (question → answer read aloud; Siri asks "For which property?" when the
> question names none, then keeps the dialog open with "Anything else?" until
> the user says no), "WHV ticket" (dictated note → ticket at the current
> property), "WHV departure/arrival", "WHV contractor on site", "WHV note to
> <contact>" (sent by our backend by e-mail). In demo mode the assistant
> answers that it is not available (it needs the company's documents); the
> other commands work on the sample data. Speech output uses
> AVSpeechSynthesizer (property briefing); speech input only via Siri.
>
> **Live Activity** shows the running trip on the Lock Screen; **Apple Watch app**
> mirrors start/end/arrival and creates a ticket by dictation. **Widgets** show
> the owner's news feed and the running trip.
>
> Target users of the manager features are our own employees (two property
> managers); owners and tenants use the same app for their portal, which is why
> the app is on the App Store.

## Release-Notes 1.3.8 („Was ist neu", App Store Connect / TestFlight)

**Deutsch**

> Neu für die Verwaltung: Fahrtenbuch mit CarPlay – Fahrten starten automatisch,
> das Zielobjekt wird erkannt, Zweck und Objekt bestätigen Sie mit einem Tipp
> im Auto. Siri versteht „WHV Abfahrt/Ankunft", „WHV Ticket" (Diktat wird zum
> Ticket), „WHV Handwerker vor Ort" und „WHV Notiz an …". „Frag WHV" ist jetzt
> ein Gespräch: Siri liest die Antwort vor und hört weiter zu. Anrufer-Erkennung
> zeigt Name, Objekt und Rolle bei eingehenden Anrufen. Objekt-Briefing zum
> Vorlesen, Fahrt als Live-Aktivität auf dem Sperrbildschirm, Apple-Watch-App,
> Wochenrückblick. Die Anfragenliste zeigt jetzt „Offen“ und „Wartend“ als
> eigene Register — erledigte Anfragen verschwinden aus der Liste. Außerdem:
> Demo-Modus für Eigentümer und Verwaltung, viele Verbesserungen und
> Fehlerbehebungen.

**English**

> New for property managers: mileage log with CarPlay – trips start
> automatically, the destination property is detected, purpose and property are
> confirmed with one tap in the car. Siri understands "WHV departure/arrival",
> "WHV ticket" (dictation becomes a ticket), "WHV contractor on site" and "WHV
> note to …". "Ask WHV" is now a conversation: Siri reads the answer and keeps
> listening. Caller ID shows name, property and role for incoming calls.
> Spoken property briefing, running trip as a Live Activity on the Lock Screen,
> Apple Watch app, weekly review. The inquiry list now has "Open" and "On hold"
> tabs — settled inquiries drop out of the list. Also: demo mode for owners and
> managers, many improvements and bug fixes.

## Woran Apple sich stören könnte — und wie wir es vorbeugen

- **„Business app in disguise."** Deshalb führt der Antrag mit dem Fahrtenbuch
  und nennt jede Funktion als Teil der Fahrt (Ziel wählen, am Ziel anrufen,
  Fahrt protokollieren). Die Ticket-Liste heißt bewusst „Today" und ist
  read-only; Ticket-*Details* bleiben auf dem Telefon.
- **Ablenkung.** Kein Freitext, keine Dokumente, max. vier Kacheln. Das steht
  explizit drin.
- **„Warum nicht Apple Maps?"** Wir ersetzen Maps nicht, wir übergeben an Maps.
  Auch das steht drin.

Sollte Apple ablehnen: Plan B ist das Fahrtenbuch rein auf dem Telefon
(automatischer Start über CarPlay-/Bluetooth-Verbindung funktioniert auch ohne
CarPlay-UI) plus Siri-App-Intents für „Frag WHV" — beides braucht kein Entitlement.

## Parallel möglich, ohne auf Apple zu warten

Im **iOS-Simulator** läuft CarPlay (I/O → External Displays → CarPlay) bereits,
wenn der Entitlement-Schlüssel in der lokalen `.entitlements`-Datei steht — die
Freigabe durch Apple braucht man erst für Geräte-Builds und den Store. Die
Templates lassen sich also jetzt schon bauen und zeigen.

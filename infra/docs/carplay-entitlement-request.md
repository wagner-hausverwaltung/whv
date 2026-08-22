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

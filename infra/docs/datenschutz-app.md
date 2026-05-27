# Datenschutzerklärung — Wagner Hausverwaltung App & Portal

> **Hinweis für die Bearbeitung:** Dieser Text ist ein Entwurf. Vor Veröffentlichung
> bitte durch einen Anwalt prüfen lassen. Die Spec-Quellen sind im Repo:
> Datenverarbeitung → `REQUIREMENTS.md` §1.4 (Impower-Spiegel) und §10 (DSGVO),
> Speicherorte → Hetzner Frankfurt (Backend) + Apple iCloud Keychain
> (Geräte-Tokens) + lokale App-Group/Keychain (iOS Cache).

**Stand: {{TODO_DATUM_VOR_VERÖFFENTLICHUNG}}**

## 1. Verantwortlicher

Wagner Hausverwaltung GmbH  
Hohewartstraße 13  
70469 Stuttgart  
Deutschland  

Telefon: +49 711 …  
E-Mail: datenschutz@wagner-hausverwaltung.com  

Geschäftsführer: Dirk Ullrich

## 2. Geltungsbereich

Diese Datenschutzerklärung gilt für

* die iOS-App **Wagner Hausverwaltung** (Bundle-ID `com.wagner-hausverwaltung.portal`),
* das Web-Portal unter <https://portal.wagner-hausverwaltung.com>,
* das Admin-Portal unter <https://admin.wagner-hausverwaltung.com>,

zusammen das „Portal". Die Marketing-Website
<https://wagner-hausverwaltung.com> hat eine eigene Datenschutzerklärung.

## 3. Welche Daten wir verarbeiten

### 3.1 Beim Anlegen Ihres Zugangs

Bei der Einladung durch die Hausverwaltung übertragen wir aus unserem
Verwaltungs-Backend (Impower) folgende Stammdaten in das Portal:

* Anrede, Titel, Vorname, Nachname (bzw. Firmenname bei juristischen Personen)
* Anschrift (Straße, Hausnummer, PLZ, Ort, Land)
* E-Mail-Adresse, Telefonnummer
* Mandatsnummer, Vertragsnummern, zugeordnete Einheiten und
  Liegenschaften
* Eigentums- / Mieterstatus

**Rechtsgrundlage:** Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung —
Hausverwaltungsvertrag bzw. Mietvertrag) sowie Art. 6 Abs. 1 lit. c
DSGVO (rechtliche Verpflichtungen aus dem WEG und BGB).

### 3.2 Bei der Nutzung des Portals

* **E-Mail-Adresse und Passwort-Hash** zur Authentifizierung
* **Geräte-Sitzungen** (User-Agent, Anmeldezeitpunkt, IP-Adresse der
  Anmeldung) zur Sicherheit Ihres Kontos
* **Von Ihnen erstellte Inhalte** — Anliegen ("Tickets"),
  Kommentare zu Mitteilungen, Fragen unter ETV-Protokollen
* **Audit-Log** — Welche Aktion zu welchem Zeitpunkt von Ihrem Konto
  ausgelöst wurde (z. B. Dokumenten-Download)

**Rechtsgrundlage:** Art. 6 Abs. 1 lit. b DSGVO (Bereitstellung der
Portal-Leistungen) und Art. 6 Abs. 1 lit. f DSGVO (berechtigtes
Interesse an Missbrauchsschutz).

### 3.3 Technische Daten der iOS-App

* **App-Group-Cache** (`group.com.wagner-hausverwaltung.portal`) — letzte
  Versammlung, neuste Tickets, neuste Mitteilung. Wird ausschließlich
  lokal auf Ihrem Gerät gespeichert, damit Widgets ohne Netzwerk
  funktionieren. Verlässt das Gerät nicht.
* **Keychain** — Ihr Anmelde-Token (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`,
  ausdrücklich nicht iCloud-synchronisiert).
* **Face ID / Touch ID** — Falls aktiviert, wird die biometrische
  Auswertung lokal von iOS durchgeführt. Wir erhalten ausschließlich
  ein boolesches "erfolgreich" / "nicht erfolgreich".

### 3.4 Was wir **nicht** erfassen

* **Kein Werbe-Tracking.** Die App verwendet keine `IDFA` und zeigt
  keine `AppTrackingTransparency`-Abfrage.
* **Keine Standortdaten.**
* **Kein Zugriff auf Fotos, Kamera, Kontakte oder Mikrofon.**
* **Keine Analytics** (Google Analytics, Firebase o. ä.).

## 4. Wie lange wir Daten speichern

* **Stammdaten und Verträge:** Solange das Verwaltungsverhältnis
  besteht, danach gemäß § 257 HGB / § 147 AO bis zu 10 Jahre.
* **Audit-Log:** 24 Monate.
* **Anmelde-Sitzungen:** 30 Tage nach Inaktivität.
* **Tickets und Kommentare:** Bis Sie den Inhalt löschen oder Ihr
  Konto löschen — danach unmittelbar.
* **Lokaler App-Cache:** Bis zur Deinstallation der App.

## 5. Wer empfängt Ihre Daten

Wir geben Daten weiter an folgende Verarbeiter im Sinne von Art. 28
DSGVO:

| Empfänger | Zweck | Ort der Verarbeitung |
|---|---|---|
| Impower Software GmbH | Hausverwaltungs-Backend (Stammdaten, Verträge, Dokumente, Buchhaltung) | Deutschland |
| Hetzner Online GmbH | Hosting des Portal-Backends, Speicherung der Dokumente | Nürnberg, Deutschland |
| Resend, Inc. | Versand transaktionaler E-Mails (Einladungen, Benachrichtigungen) | EU (Amazon SES Frankfurt) — Standardvertragsklauseln Art. 46 DSGVO |
| Apple Inc. | Auslieferung der iOS-App und Push-Benachrichtigungen (sobald aktiviert) | USA — angemessenes Datenschutzniveau gemäß EU-US Data Privacy Framework |
| Google Inc. | KI-gestützte Extraktion aus PDF-Einladungen / -Protokollen (Gemini) | EU-Region — Datenverarbeitung-Vertrag, kein Trainingseinsatz |

Wir verkaufen keine Daten und geben sie nicht zu Werbezwecken weiter.

## 6. Ihre Rechte

Nach DSGVO haben Sie folgende Rechte uns gegenüber:

* **Auskunft** (Art. 15) — über das Portal: Einstellungen → Datenschutz → **Datenexport**.
* **Berichtigung** (Art. 16) — durch Nachricht an die Verwaltung.
* **Löschung** (Art. 17) — über das Portal: Einstellungen → Konto → **Konto löschen**.
  Beachten Sie, dass Verwaltungsdaten aus rechtlichen Gründen
  (Steuer, HGB) parallel im Verwaltungs-Backend verbleiben.
* **Einschränkung der Verarbeitung** (Art. 18)
* **Datenübertragbarkeit** (Art. 20) — der Datenexport im Portal liefert ein maschinenlesbares JSON.
* **Widerspruch** (Art. 21) gegen Verarbeitung auf Basis berechtigter Interessen.

Diese Rechte können Sie jederzeit unter
<datenschutz@wagner-hausverwaltung.com> geltend machen.

## 7. Beschwerderecht bei der Aufsichtsbehörde

Sie haben das Recht, sich bei einer Aufsichtsbehörde zu beschweren.
Zuständig ist insbesondere:

> Der Landesbeauftragte für den Datenschutz und die Informationsfreiheit Baden-Württemberg  
> Königstraße 10a, 70173 Stuttgart  
> <https://www.baden-wuerttemberg.datenschutz.de>

## 8. Demo-Modus

Beim Antippen von "Demo" auf dem Anmeldebildschirm wird die App
ausschließlich mit Beispieldaten gefüllt, die direkt im App-Binary
hinterlegt sind. Es findet keine Datenübertragung an unsere Server
statt; es entstehen keine Konten. Diese Funktion dient nur der
Vorstellung der App, etwa im App-Store-Review-Prozess.

## 9. Sicherheit

* TLS 1.2 oder höher für jede Datenübertragung
* Argon2id-Passwort-Hashing
* Geräte-Sitzungen werden bei Verdacht serverseitig revoziert
* Postgres-Datenbank mit Festplattenverschlüsselung
* Backups verschlüsselt, in derselben Rechtsregion gespeichert

## 10. Änderungen dieser Erklärung

Bei wesentlichen Änderungen informieren wir betroffene Nutzerinnen
und Nutzer per E-Mail und im Portal. Das Datum am Anfang dieser
Erklärung verweist auf die aktuell gültige Fassung.

# ADR-0020 — Fahrtenbuch, CarPlay (Driving Task) und Auslagen-Rechnung Fahrtkosten

**Status:** accepted (Phasen 1–5 umgesetzt, 2026-08-21 … 2026-08-23)
**Date:** 2026-08-23 (nachgetragen; Code zitiert diese ADR seit 2026-08-21)
**Deciders:** Luis Wagner

## Context

Dirk Ullrich (Verwalter) fährt mit seinem **privaten** Auto (BYD Dolphin Surf,
CarPlay) zwischen Büro, Objekten, Besichtigungen und Versammlungen. Gewünscht:
ein Fahrtenbuch mit Kilometergeld, eine CarPlay-Oberfläche rund um die Fahrt
und — Phase 5 — die Weiterberechnung von Fahrtkosten an das Objekt.

Net-new scope gegenüber `REQUIREMENTS.md`, daher diese ADR.

## Decisions

1. **Kein Finanzamt-Fahrtenbuch.** Das Auto ist privat → WHV zahlt dem Fahrer
   Kilometergeld (0,30 €/km, `trip_rate_cents_per_km`, als Snapshot je Fahrt).
   GPS-Strecke genügt; kein Tachostand, Manipulationsschutz nur über Audit-Log.
   Modell `Trip` (RUNNING → OPEN → CONFIRMED; Quellen AUTO/MANUAL/CARPLAY;
   Zweck frei als Text mit StrEnum-Validierung; PRIVAT wird geloggt, nie vergütet).
2. **Erfassung am Telefon** (Core Motion automotive + Location, Opt-in als
   Einwilligung), Upload als eine fertige Fahrt, Bestätigung von Zweck/Objekt
   mit Vorschlag „nächstes Objekt ≤ 300 m" von der Endposition.
3. **CarPlay = Driving Task** (Apple-Entitlement erteilt 2026-08-23, Case-ID
   21774792). Die Fahrt ist das Zentrum (Addendum § 3.10: keine POI-Liste):
   Fahrt starten/beenden (Zweck im Auto bestätigen), Objekte → Navigation
   (Apple Maps), Besichtigung (Anfragen aus anfragen@, Fahrt ↔ Anfrage
   verknüpft), Kontakte (Anrufen, „verspäte mich" per Server-Mail), Heute
   (Termine org-weit via `/me/agenda` + Activity-Feed). Sprachdialog (RAG) läuft
   über Siri App Intents („Frag WHV", „WHV Ticket"), nicht über CarPlay.
   Harte Limits: Stacktiefe 2 unter Root, Listen ≤ `maximumItemCount`.
4. **Auslagen-Rechnung je Objekt (Phase 5) ist vertragsabhängig, deshalb
   Auswahl statt Automatik.** Die Verträge erlauben nicht „alle Fahrten":
   - WEG-Verwaltervertrag (WHV-Muster 2025) **§ 8.3.2**: Fahrtkosten nur für
     Beirats-/Eigentümerversammlungen **außerhalb Kreis Stuttgart**, zu
     steuerrechtlichen Sätzen (derzeit 0,42 €/km).
   - VDIV-2026 MV/SEV **§ 5.3/5.4**: Fahrten Verwaltung ↔ Objekt sind in der
     monatlichen Auslagenpauschale abgegolten; „im Übrigen" 0,50 €/km.
   Daher: `GET /admin/trips/billable` liefert die offenen bestätigten Fahrten
   eines Objekts plus Default-Regel (WEG: ETV vorgehakt, 0,42; MV/SEV: nichts
   vorgehakt, 0,50), der Verwalter wählt Fahrten und Satz, `POST
   /admin/trips/invoices` erzeugt eine **unveränderliche** Rechnung
   (`trip_invoices`: Snapshot der Zeilen, Nummer `WHV-FK-JJJJ-NNNN` fortlaufend
   je Org und Jahr, 19 % USt auf den Nettobetrag), markiert die Fahrten
   (`trips.invoice_id`) und rendert das PDF aus dem Snapshot. Nur die zuletzt
   nummerierte Rechnung darf storniert werden (lückenlose Folge, § 14 UStG /
   GoBD-Gedanke); Älteres braucht eine Gutschrift außerhalb des Tools.
   Firmendaten für den PDF-Fuß: `app/integrations/pdf/company.py` (aus dem
   Vertrags-Template übernommen).
5. **Kilometergeld ≠ Weiterberechnung.** Die Kilometergeld-Abrechnung je Fahrer
   (`statement.pdf`, 0,30 €/km, „Auslagen je Objekt" als interne Zuordnung) und
   die Rechnung an das Objekt (0,42/0,50 €/km zzgl. USt) sind getrennte
   Dokumente mit getrennten Sätzen.

## Consequences

- Akquise-Fahrten (Besichtigung von Anfragen) bleiben Kilometergeld ohne
  Objekt und sind nie weiterberechenbar.
- Der Zahlungsweg der Rechnung ist die Belastung des Objektkontos durch den
  Verwalter (Text auf dem PDF); Buchung in Impower erfolgt manuell.
- Offene Punkte: Satzanpassung laut Staffelklausel (VDIV § 5.5), englische
  Übersetzungen der iOS-Strings, Realtest CarPlay am Gerät.

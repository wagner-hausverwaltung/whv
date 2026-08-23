# Host-Betrieb: whv-prod-api / whv-staging-api

Die Hetzner-Hosts (prod `91.99.123.40`, staging `46.225.185.151`, beide Ubuntu
24.04 arm64) schicken jede Nacht eine **host-health**-Mail (systemd-Unit
`host-health.service`, Skript aus dem separaten `slr-pipeline`-Repo) an
wagner@. Verdict FAIL/WARN/ok; der Unit selbst steht nach einem FAIL/WARN
absichtlich auf `failed` (Exit 2) — das ist kein zweiter Fehler.

Dieses Dokument sammelt die Meldungen, die schon einmal aufgetreten sind,
mit Ursache und dem, was getan wurde. Ergänzen, wenn eine neue dazukommt.

## `systemd FAIL: failed units: cloud-init-hotplugd.service` (prod, 2026-08-23)

**Ursache.** cloud-init installiert auf Hetzner eine udev-Regel
(`/etc/udev/rules.d/90-cloud-init-hook-hotplug.rules`), die bei `net add`
für Interfaces mit MAC-Präfix `86:` den Hotplug-Hook startet. Docker legt
bei jedem `compose up` veth-Interfaces mit zufälligen MACs an — fängt eine
davon mit `86:` an, sucht cloud-init diese MAC 80 s lang in den
Hetzner-Metadaten, findet sie nicht (`RuntimeError: Failed to detect … in
updated metadata`) und der Unit bleibt `failed`. Rein kosmetisch, aber ein
FAIL in der Nachtmail — und zufällig bei jedem Deploy möglich.

**Fix (auf prod UND staging angewendet, 2026-08-23).**

```
# /etc/cloud/cloud.cfg.d/95-whv-no-hotplug.cfg
#cloud-config
updates:
  network:
    when: ["boot", "boot-new-instance"]   # Hetzner-Default minus "hotplug"
```

plus einmalig `rm /etc/udev/rules.d/90-cloud-init-hook-hotplug.rules`,
`udevadm control --reload-rules`, `systemctl reset-failed
cloud-init-hotplugd.service`. Beim nächsten Boot hält `cc_install_hotplug`
die Regel von selbst fern, weil Hotplug nicht mehr zu den erlaubten Events
gehört. Prüfen: `cloud-init schema --config-file …95-whv-no-hotplug.cfg`
→ „Valid schema". Rückgängig: Datei löschen, Host neu starten.

Wirkung: cloud-init konfiguriert das Netzwerk nicht mehr nach, wenn zur
Laufzeit eine NIC dazukommt (Hetzner Private Network o. ä.) — dafür reicht
dann ein Reboot. Für unsere Single-NIC-Boxen irrelevant.

## `updates WARN: N regular update(s) pending` (staging, 2026-08-23)

unattended-upgrades installiert nur Security-Updates; „regular" Pakete
(z. B. `console-setup`, `keyboard-configuration`) bleiben liegen, bis jemand
`apt-get update && apt-get upgrade` macht. Gefahrlos per SSH:

```bash
ssh root@46.225.185.151 'DEBIAN_FRONTEND=noninteractive apt-get update -qq && apt-get upgrade -y -qq'
```

Pakete, die Ubuntu noch „phased" ausrollt (`apt-get -s upgrade` →
„deferred due to phasing", z. B. `open-vm-tools`), bleiben absichtlich
stehen und kommen von selbst.

## Journal-Größe auf prod

`journalctl --disk-usage` zeigte am 2026-08-23 **2,1 GB** (staging: 31 MB) —
Altlast aus den nächtlichen Celery-OOM-Schleifen (siehe
`backend/app/rag/extraction.py`, behoben im Aug 2026). Noch unkritisch
(Disk 36 %), bei Bedarf `journalctl --vacuum-size=500M`.

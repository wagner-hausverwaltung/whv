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

## Wartung 2026-08-26 (beide Hosts, WARN „regular updates")

Erledigt per SSH, ohne Ausfall (`healthz` vor und nach 200, Container
unverändert gesund, kein Reboot nötig):

```bash
ssh root@<host> 'DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a \
  apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade'
```

* **staging**: `open-vm-tools`. Übrig bleibt `byobu` — **phased 40 %**, kommt von selbst.
* **prod**: `console-setup*`, `keyboard-configuration`, `open-vm-tools`, `byobu` — und
  zusätzlich **`openssl`/`libssl3t64` (Security) sowie `vim`/`xxd`**, die im Mail von
  07:38 noch nicht standen. `needrestart` hat die betroffenen Host-Dienste selbst
  neugestartet („No containers need to be restarted" — die Container bringen ihr
  eigenes libssl mit). Übrig bleiben `python3.12*`, `procps`, `libproc2-0` — alle phased.

`NEEDRESTART_MODE=a` ist hier wichtig: ohne das fragt `needrestart` interaktiv und der
Lauf hängt. `--force-confold` behält die eigenen Configs (u. a. die Caddy-/cloud-init-Anpassungen).

### `host-health.service` selbst taucht als „failed unit" auf

Der Check beendet sich bei Verdict WARN/FAIL mit Exit 1 — systemd merkt sich das als
`failed`. Der **nächste saubere Lauf setzt das von allein zurück**; solange aber irgendetwas
warnt, meldet die Folgenacht zusätzlich „1 failed unit" und warnt damit über sich selbst.
Nach einer Wartung deshalb aufräumen:

```bash
ssh root@<host> 'systemctl reset-failed host-health.service'
```

Phased-Pakete meldet der Check übrigens korrekt NICHT: er liest `apt-get -s upgrade`
und zählt nur `^Inst`-Zeilen; zurückgehaltene Pakete stehen dort unter „deferred due to
phasing".

## Updates laufen jetzt automatisch (beide Hosts, 2026-08-28)

Bis hierher installierte `unattended-upgrades` nur **Security**-Pakete; alles aus
dem `-updates`-Pocket (python3.12, procps, open-vm-tools, console-setup, byobu …)
blieb liegen und erzeugte Nacht für Nacht eine host-health-WARN, auf die ohnehin
nur jemand mit `apt-get upgrade` reagierte. Zwei Drop-ins schalten das um — als
eigene Dateien, damit ein Paket-Update von `unattended-upgrades` sie nicht
überschreibt und ein `rm` genügt, um zurückzugehen:

* `/etc/apt/apt.conf.d/52whv-unattended-updates`
  * `Allowed-Origins:: "${distro_id}:${distro_codename}-updates"` — reguläre Updates dazu.
  * `Automatic-Reboot "false"` — **Neustarts bleiben manuell**; host-health meldet
    weiterhin „reboot pending", die Entscheidung trifft ein Mensch.
* `/etc/needrestart/conf.d/50-whv-auto.conf` → `$nrconf{restart} = 'a';`
  Ohne das aktualisiert der Lauf zwar die Pakete, die laufenden Prozesse hängen
  aber weiter an der alten Bibliothek (needrestart steht sonst auf `i`,
  interaktiv, und tut im automatischen Lauf nichts).

**Warum das vertretbar ist:** `docker-ce` kommt von `download.docker.com`, nicht
aus Ubuntus Pocket — die Container-Laufzeit fällt **nicht** unter die neue Origin
und bleibt unter manueller Kontrolle. needrestart fasst Container ohnehin nicht an
(„No containers need to be restarted"). Kernel-Updates führen weiterhin nur zu
„reboot pending", nie zu einem selbsttätigen Neustart.

Geprüft: `unattended-upgrade --dry-run --debug` zeigt `a=noble-updates` in den
Allowed origins; auf staging lief ein echter Durchlauf durch (danach 0 offene
Pakete, 12 Container gesund, `healthz` 200).

Zurückdrehen: die beiden Dateien löschen, fertig.

## `host-health.service` meldete sich selbst als „failed" — behoben (2026-08-28)

Das Skript beendet sich bei WARN/FAIL mit Exit ≠ 0, systemd merkt sich den Lauf
dadurch als `failed` — und der **nächste** Lauf las das als „failed unit" und
machte aus einer Warnung einen **FAIL**, der sich selbst am Leben hielt, bis
jemand `systemctl reset-failed` ausführte. Am 2026-08-28 auf staging genau so
passiert: 07:34 WARN wegen offener Updates, der Folgelauf meldete FAIL, obwohl
die Updates längst installiert waren.

Fix im Repo **`slr-pipeline`** (Commit e2fb830, `scripts/host-health.sh`): die
eigene Unit wird aus der Liste gefiltert (überschreibbar per `HOST_HEALTH_UNIT`),
andere failed units zählen unverändert. Test deckt beide Fälle ab. Das Skript
liegt auf den Hosts unter `/usr/local/sbin/host-health` und wurde dort ersetzt —
bei einem erneuten `install-host-health.sh` kommt es ohnehin aus dem Repo.

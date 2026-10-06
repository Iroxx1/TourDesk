# TourDesk – Schnellstart

## 1. Container anlegen (Proxmox)

*CT erstellen* → unprivilegiert, **Debian 12** (oder Ubuntu 24.04), 2 Kerne, 2 GB RAM,
12 GB Disk, Netzwerk per DHCP oder feste IP → starten → Konsole öffnen.

## 2. Installieren

```bash
apt update && apt install -y git
git clone https://github.com/iroxx1/tourdesk.git /opt/tourdesk
cd /opt/tourdesk
./install.sh
```

Das Skript fragt nach dem Admin-Benutzer (leer lassen = später im Browser anlegen) und
richtet Datenbank, Backend, Frontend, Crawler und Scheduler als systemd-Dienste ein.
Docker statt nativ: `./install.sh --docker` (im LXC dafür `nesting=1,keyctl=1` aktivieren).

## 3. Loslegen

1. Im Browser **`http://<IP-des-Containers>:8080`** öffnen und anmelden
   (bzw. Admin-Konto in der Ersteinrichtung erstellen).
2. *Administration → Benutzer → Neu*: weitere Benutzer anlegen.
3. Startmenü (TourDesk-Logo unten links) → **Künstler** → Künstler suchen und hinzufügen.
   Zum Ausprobieren: **„Beispielband“** liefert sofort Demo-Termine.
4. Startmenü → **Filter**: Regionen (z. B. *Saarland*), Städte (z. B. *Metz*) und einzelne
   Veranstaltungsorte (z. B. *Rockhal*) hinzufügen.
5. Im Künstlerfenster den Schalter **„Festivals anzeigen“** setzen.
6. Termine erscheinen auf den Kacheln; der Crawler aktualisiert ungefähr stündlich
   (sofort: *Jetzt aktualisieren* im Künstlerfenster).

Beispielbenutzer aus der Anleitung (Backstreet Boys, Metallica, Linkin Park, Beispielband;
Saarland komplett, Luxemburg nur Rockhal/Messegelände, Frankreich nur Metz/Straßburg):

```bash
tourdesk example-config
```

## 4. Betrieb

| Aufgabe | Befehl |
|---------|--------|
| Status | `systemctl status tourdesk-api tourdesk-worker tourdesk-scheduler` · `tourdesk status` |
| Logs | `journalctl -u 'tourdesk-*' -f` · Administration → Logs |
| Backup | `./scripts/backup.sh` (mit Bildern: `--with-media`) |
| Restore | `./scripts/restore.sh backups/tourdesk-….tar.gz` |
| Update | `./scripts/update.sh` |
| Admin-Passwort zurücksetzen | `tourdesk reset-password --username admin --generate-password` |

## 5. Von außen erreichbar machen (optional)

Cloudflare Zero Trust → *Networks → Tunnels* → Tunnel anlegen → Public Hostname
`tourdesk.meinedomain.de` → Service `HTTP localhost:8080`. Im Container:

```bash
# cloudflared installieren (siehe README) und Tunnel-Token einrichten
cloudflared service install <TUNNEL-TOKEN>
cd /opt/tourdesk && ./install.sh --public-url https://tourdesk.meinedomain.de --no-admin --yes
```

Alles Weitere: **[README.md](README.md)**.

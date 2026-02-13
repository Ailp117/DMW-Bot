# DMW Raid Bot

Ein Discord-Bot zur Planung, Verwaltung und Nachverfolgung von Raids inkl. persistenter Listen, Attendance-Tracking, Levelsystem und DB-Backups.

## Features

- Slash-Command-basierte Raidplanung (`/raidplan`) mit persistenter Raidliste.
- Teilnehmer-/Memberlisten mit Wiederherstellung nach Neustart.
- Template- und Settings-Verwaltung direkt im Bot.
- Attendance-Tracking per Commands.
- Temporäre Rollen für Raid-Organisation.
- Level-/XP-System inkl. Voice-XP-Intervallen.
- Automatische Datenbank-Schema-Anpassung beim Start (fehlende Tabellen/Spalten aller Bot-Modelle werden ergänzt).
- Self-Tests, Logging und Health-Checks für den Betrieb.
- Boot-Smoke-Checks beim Start (DB erreichbar, Pflichttabellen, offene Raids).
- Automatische und manuelle SQL-Backups.

## Voraussetzungen

- Python **3.11+**
- PostgreSQL (asynchron über `asyncpg`)
- Discord Bot Token mit passenden Berechtigungen

## Installation

1. Repository klonen.
2. Gepinnte Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
```

3. Optional: zweitneueste stabile Versionen neu auflösen (für lokale Updates):

```bash
python scripts/resolve_second_latest_requirements.py --input requirements.in --output requirements.txt
```

4. Umgebungsvariablen setzen (siehe unten).
5. Bot starten:

```bash
python main.py
```

## Konfiguration (.env / GitHub Secrets)

Mindestens erforderlich:

```env
DISCORD_TOKEN=dein_discord_bot_token
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

Wichtige optionale Variablen:

```env
DB_ECHO=0
ENABLE_MESSAGE_CONTENT_INTENT=true
LEVEL_PERSIST_INTERVAL_SECONDS=120
MESSAGE_XP_INTERVAL_SECONDS=15
LEVELUP_MESSAGE_COOLDOWN_SECONDS=20

LOG_GUILD_ID=0
LOG_CHANNEL_ID=0
DISCORD_LOG_LEVEL=DEBUG

SELF_TEST_INTERVAL_SECONDS=900
BACKUP_INTERVAL_SECONDS=21600

RAIDLIST_DEBUG_CHANNEL_ID=0
MEMBERLIST_DEBUG_CHANNEL_ID=0
```

Für GitHub Actions (`.github/workflows/bot.yml`) werden mindestens diese Secrets erwartet:

- `DISCORD_TOKEN`
- `DATABASE_URL`

Zusätzlich unterstützt der Bot (optional) diese Secrets/ENVs aus `config.py`:

- `DB_ECHO`
- `ENABLE_MESSAGE_CONTENT_INTENT`
- `LOG_GUILD_ID`
- `LOG_CHANNEL_ID`
- `DISCORD_LOG_LEVEL`
- `SELF_TEST_INTERVAL_SECONDS`
- `BACKUP_INTERVAL_SECONDS`
- `RAIDLIST_DEBUG_CHANNEL_ID`
- `MEMBERLIST_DEBUG_CHANNEL_ID`


## Wichtige Commands (Auszug)

- `/raidplan` – neuen Raid planen
- `/raidlist` – aktuelle Raidliste anzeigen
- `/dungeonlist` – aktive Dungeons anzeigen
- `/settings` – Bot-Einstellungen verwalten
- `/template_config` – Raid-Templates konfigurieren
- `/cancel_all_raids` – alle offenen Raids abbrechen (Admin)
- `/backup_db` – manuelles DB-Backup (privilegierter Nutzer)
- `/status` – Bot-Status prüfen
- `/help` / `/help2` – Hilfe anzeigen

## Raid-Teilnahmezaehler (DB-only)

- Bei `raid_finish` wird pro teilnehmendem User ein Eintrag in `raid_attendance` gespeichert.
- Der Teilnahmezaehler startet bei `0` und steigt pro abgeschlossenen Raid mit Teilnahme um `+1`.
- Der aktuelle Wert ergibt sich aus der Anzahl der `present`-Eintraege in `raid_attendance` pro `guild_id + user_id`.
- Es gibt dafuer aktuell bewusst keinen Slash-Command; Speicherung erfolgt nur in der Datenbank.

## Backups

- **Automatisch:** zyklisch über `BACKUP_INTERVAL_SECONDS` (Default: 21600s = 6h).
- **Manuell:** per `/backup_db`.
- **Speicherort:** `backups/db_backup.sql`.

## Tests

```bash
pytest
```

Die Tests decken u. a. Command-Registrierung, Berechtigungen, Konfigurationslogik, DB-Logging und View-/Raid-Regressionen ab.

## Projektstruktur (Kurzüberblick)

- `main.py` – Bot-Lifecycle, Task-Scheduling, Command-Registrierung
- `commands_*.py` – Slash-Command-Module nach Themen
- `views_*.py` – Discord UI Views
- `models.py` – SQLAlchemy-Modelle
- `db.py` – DB-Engine, Session-Handling, SQL-Logging
- `ensure_schema.py` – Schema-Initialisierung/-Migration
- `backup_sql.py` – SQL-Export/Backup
- `tests/` – automatisierte Tests
- `FEATURE_MATRIX.md` – Zuordnung Feature → Code → DB → Tests

## Hinweise für den Betrieb

- Der Bot nutzt einen Singleton-Lock in Postgres, um Doppel-Instanzen zu vermeiden.
- Stelle sicher, dass der Bot die nötigen Channel- und Rollenrechte im Discord-Server besitzt.
- Bei Produktionsbetrieb sollten Logs und Backups regelmäßig überwacht werden.

## CI / 24-7-Strategie

- Der Runtime-Workflow startet alle 6 Stunden neu (`schedule`) und zusätzlich manuell via `workflow_dispatch`.
- Ein Monatsend-Job aktualisiert `requirements.txt` automatisch auf zweitneueste stabile Releases.
- Wenn ein Direkt-Push auf den Ziel-Branch blockiert ist (z. B. Branch-Protection), erstellt der Monatsend-Job automatisch ein Fallback-PR.
- Auf jedem Push/PR läuft `pytest -q`; bei Fehlern schlägt CI fehl.
- Durch `concurrency` wird nur eine Runtime-Instanz aktiv gehalten.
- Ein harter 24/7-Betrieb ist auf GitHub-Hosted-Runnern nur "24/7-ish" möglich, daher der periodische Neustart als Stabilitätsstrategie.

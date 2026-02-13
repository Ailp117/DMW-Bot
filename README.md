# DMW Raid Bot

Ein Discord-Bot zur Planung, Verwaltung und Nachverfolgung von Raids inkl. persistenter Listen, Attendance-Tracking, Levelsystem und DB-Backups.

## Features

- Slash-Command-basierte Raidplanung (`/raidplan`) mit persistenter Raidliste.
- Teilnehmer-/Memberlisten mit Wiederherstellung nach Neustart.
- Template- und Settings-Verwaltung direkt im Bot.
- Attendance-Tracking per Commands.
- Temporäre Rollen für Raid-Organisation.
- Level-/XP-System inkl. Voice-XP-Intervallen.
- Automatische Datenbank-Schema-Sicherung beim Start.
- Self-Tests, Logging und Health-Checks für den Betrieb.
- Automatische und manuelle SQL-Backups.

## Voraussetzungen

- Python **3.11+**
- PostgreSQL (asynchron über `asyncpg`)
- Discord Bot Token mit passenden Berechtigungen

## Installation

1. Repository klonen.
2. Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
```

3. Umgebungsvariablen setzen (siehe unten).
4. Bot starten:

```bash
python main.py
```

## Konfiguration (.env)

Mindestens erforderlich:

```env
DISCORD_TOKEN=dein_discord_bot_token
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

Wichtige optionale Variablen:

```env
DB_ECHO=0
ENABLE_MESSAGE_CONTENT_INTENT=true

LOG_GUILD_ID=0
LOG_CHANNEL_ID=0
DISCORD_LOG_LEVEL=DEBUG

SELF_TEST_INTERVAL_SECONDS=900
BACKUP_INTERVAL_SECONDS=21600

RAIDLIST_DEBUG_CHANNEL_ID=0
MEMBERLIST_DEBUG_CHANNEL_ID=0
```

## Wichtige Commands (Auszug)

- `/raidplan` – neuen Raid planen
- `/raidlist` – aktuelle Raidliste anzeigen
- `/dungeonlist` – aktive Dungeons anzeigen
- `/attendance_list` – Attendance-Liste anzeigen
- `/attendance_mark` – Attendance markieren
- `/settings` – Bot-Einstellungen verwalten
- `/template_config` – Raid-Templates konfigurieren
- `/cancel_all_raids` – alle offenen Raids abbrechen (Admin)
- `/backup_db` – manuelles DB-Backup (privilegierter Nutzer)
- `/status` – Bot-Status prüfen
- `/help` / `/help2` – Hilfe anzeigen

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

## Hinweise für den Betrieb

- Der Bot nutzt einen Singleton-Lock in Postgres, um Doppel-Instanzen zu vermeiden.
- Stelle sicher, dass der Bot die nötigen Channel- und Rollenrechte im Discord-Server besitzt.
- Bei Produktionsbetrieb sollten Logs und Backups regelmäßig überwacht werden.

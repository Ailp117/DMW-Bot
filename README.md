# DMW Raid Bot

Ein Discord-Bot zur Planung, Verwaltung und Nachverfolgung von Raids mit persistenter Raidliste, automatischen Teilnehmerlisten, Attendance-Tracking, Levelsystem und mehr.

## Features

### Raid-Management
- **Raid-Planung** (`/raidplan`): Erstelle Raids mit Datum, Uhrzeit und Mindestteilnehmern via Modal
- **Automatische Raidliste**: Übersicht aller offenen Raids mit qualifizierten Slots
- **Teilnehmerlisten**: Automatisch erstellte Listen für jeden Zeit-Slot
- **Attendance-Tracking**: Automatische Speicherung bei Raid-Abschluss
- **Temporäre Rollen**: Für Raid-Organisation und Reminder

### Level-System
- Message-XP mit konfigurierbaren Intervallen
- Voice-XP für Zeit in Voice-Channels
- Level-Up Benachrichtigungen
- Persistente Level-Speicherung

### Administration
- Template-System für wiederkehrende Raids
- Remote-Commands für Multi-Server Management
- Automatische Datenbank-Backups
- Self-Tests und Health-Checks
- Singleton-Lock für sicheren Betrieb

## Schnellstart

### Voraussetzungen
- Python 3.12+
- PostgreSQL (optional, siehe [In-Memory-Modus](#in-memory-modus-für-testing))
- Discord Bot Token

### Installation

```bash
# Repository klonen
git clone <repo-url>
cd DMW-Bot

# Virtuelle Umgebung erstellen
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# oder: .venv\Scripts\activate  # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt

# Konfiguration kopieren
cp .env.example .env
```

### Konfiguration

Bearbeite die `.env` Datei:

```env
# Erforderlich
DISCORD_TOKEN=dein_discord_bot_token

# Für normalen Betrieb mit Datenbank
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# Für lokales Testing (keine Datenbank nötig)
USE_IN_MEMORY_DB=true
```

### Bot starten

```bash
# Normaler Betrieb
python -m bot.runtime

# Mit In-Memory-DB (Testing)
USE_IN_MEMORY_DB=true python -m bot.runtime
```

## Commands

### Raid-Management
| Command | Beschreibung |
|---------|-------------|
| `/raidplan <dungeon>` | Neuen Raid erstellen |
| `/raid_finish <raid_id>` | Raid abschließen (nur Ersteller) |
| `/raidlist` | Raidliste aktualisieren/anzeigen |
| `/cancel_all_raids` | Alle offenen Raids abbrechen (Admin) |

### Einstellungen
| Command | Beschreibung |
|---------|-------------|
| `/settings` | Bot-Konfiguration (Channels, Features) |
| `/template_config` | Templates aktivieren/deaktivieren |
| `/status` | Bot-Status und Gesundheit |

### Administration
| Command | Beschreibung |
|---------|-------------|
| `/backup_db` | Manuelles Datenbank-Backup |
| `/remote_guilds` | Liste verbundener Server |
| `/remote_cancel_all_raids` | Raids auf anderem Server canceln |
| `/remote_raidlist` | Raidlist auf anderem Server refreshen |
| `/purge <n>` | Letzte n Nachrichten löschen |
| `/restart` | Bot neustarten (privilegierter User) |

### Hilfe
| Command | Beschreibung |
|---------|-------------|
| `/help` | Verfügbare Commands |
| `/help2` | Detaillierte Anleitung |
| `/id` | Deine XP-ID Card |

## In-Memory-Modus für Testing

Für lokale Entwicklung kannst du den Bot ohne Datenbank starten:

```bash
USE_IN_MEMORY_DB=true python -m bot.runtime
```

**Vorteile:**
- Keine PostgreSQL-Installation nötig
- Alle Daten werden im RAM gehalten
- Keine Persistenz (Daten gehen beim Beenden verloren)
- Ideal für Tests ohne echte Daten zu verändern

## VS Code Debugging

Die `.vscode/launch.json` enthält vorkonfigurierte Debug-Profile:

1. **Bot: In-Memory (Local)** - Testing ohne DB
2. **Bot: Full Local** - Mit lokaler PostgreSQL

Drücke `F5` in VS Code um den Debugger zu starten.

## Konfiguration

### Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|-------------|----------|
| `DISCORD_TOKEN` | Discord Bot Token (erforderlich) | - |
| `DATABASE_URL` | PostgreSQL Verbindungs-URL | - |
| `USE_IN_MEMORY_DB` | In-Memory-Modus aktivieren | false |
| `PRIVILEGED_USER_ID` | Admin User ID | 403988960638009347 |
| `LOG_GUILD_ID` | Guild für Log-Channel | 0 |
| `LOG_CHANNEL_ID` | Channel für Logs | 0 |
| `RAIDLIST_DEBUG_CHANNEL_ID` | Debug-Channel für Raidlist | 0 |
| `MEMBERLIST_DEBUG_CHANNEL_ID` | Debug-Channel für Memberlist | 0 |
| `SELF_TEST_INTERVAL_SECONDS` | Intervall für Self-Tests | 900 |
| `BACKUP_INTERVAL_SECONDS` | Intervall für Backups | 21600 |

### Feature-Einstellungen

Über `/settings` konfigurierbar:

- `leveling_enabled` - XP-System aktivieren
- `levelup_messages_enabled` - Level-Up Benachrichtigungen
- `nanomon_reply_enabled` - Nanomon-Keyword Reaktionen
- `approved_reply_enabled` - Approved-Keyword Reaktionen
- `raid_reminder_enabled` - Automatische Raid-Erinnerungen
- `message_xp_interval_seconds` - XP-Interval für Messages
- `levelup_message_cooldown_seconds` - Cooldown für Level-Up Nachrichten

## Raid-Erstellung Workflow

1. User gibt `/raidplan <Dungeon>` ein
2. Bot öffnet Modal mit:
   - Datum (Text, z.B. "20.02.2026, 21.02.2026")
   - Uhrzeiten (Text, z.B. "20:00, 21:00")
   - Min. Spieler (Zahl)
3. Bot erstellt Raid und postet:
   - Planner-Message im Umfragen-Channel
   - Teilnehmerlisten für qualifizierte Slots
   - Aktualisierte Raidliste

## Datenbank-Schema

Der Bot erstellt automatisch alle benötigten Tabellen:

- `settings` - Guild-Konfigurationen
- `dungeons` - Verfügbare Dungeons
- `raids` - Offene/abgeschlossene Raids
- `raid_options` - Tage/Zeiten pro Raid
- `raid_votes` - User-Votes pro Option
- `raid_posted_slots` - Gepostete Teilnehmerlisten
- `raid_templates` - Auto-Templates
- `raid_attendance` - Teilnahme-Tracking
- `user_levels` - XP und Levels
- `debug_cache` - Debug-Message Caching

## Backups

- **Automatisch**: Alle 6 Stunden (konfigurierbar)
- **Manuell**: Via `/backup_db`
- **Speicherort**: `backups/db_backup.sql`

## Testing

```bash
# Alle Tests ausführen
pytest

# Mit Coverage
pytest --cov

# Spezifischen Test
pytest tests/test_phase3_raidlist_embed.py -v
```

## Projektstruktur

```
DMW-Bot/
├── bot/
│   ├── runtime.py          # Haupt-Bot Klasse
│   ├── config.py           # Konfiguration
│   └── discord_api.py      # Discord.py Layer
├── commands/
│   └── runtime_commands.py # Slash-Commands
├── features/
│   └── runtime_mixins/     # Feature-Module
│       ├── events.py       # Lifecycle
│       ├── logging_background.py  # Logs & Worker
│       ├── raid_ops.py     # Raid-Operationen
│       └── state_calendar.py      # State-Management
├── services/               # Business-Logik
│   ├── raid_service.py
│   ├── leveling_service.py
│   └── persistence_service.py
├── db/                     # Datenbank
│   ├── models.py
│   ├── repository.py
│   └── session.py
├── views/                  # Discord UI
│   └── raid_views.py
├── utils/                  # Hilfsfunktionen
│   └── runtime_helpers.py
└── tests/                  # Tests
```

## Betriebshinweise

### Singleton-Lock
Der Bot nutzt einen Postgres Advisory Lock um Doppel-Instanzen zu vermeiden.

### Berechtigungen
Der Bot benötigt:
- Slash-Command Registrierung
- Nachrichten lesen/schreiben
- Reaktionen hinzufügen
- Rollen verwalten (für Temp-Rollen)
- Channel-Historie lesen

### Logging
- Lokal: Console/Terminal
- Discord: Terminal-ähnliches Embed im konfigurierten Log-Channel
- Logs werden gebündelt alle 5 Sekunden gesendet und aktualisiert

## CI/CD

### GitHub Actions

- **Bot-Workflow**: Startet alle 6 Stunden neu
- **Tests**: Laufen bei jedem Push/PR
- **Dependency Updates**: Monatlich automatisch

### 24/7-Betrieb

- Periodischer Neustart alle 6h als Stabilitätsstrategie
- Concurrency-Setting: Nur eine Instanz aktiv
- Automatische Backups

## Support

Bei Problemen oder Fragen:
1. Prüfe die Logs (lokal oder im Log-Channel)
2. Führe `/status` aus für Bot-Gesundheit
3. Checke die Self-Test Ergebnisse

## Lizenz

[MIT License](LICENSE)

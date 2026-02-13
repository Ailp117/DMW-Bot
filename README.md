# DMW Raid Bot

Discord Raid Planer Bot mit:
- Persistenter Raidlist
- Teilnehmerlisten pro Tag & Uhrzeit
- Temporären Rollen
- Vollständiger DB Auto-Migration
- Admin & Settings Menü

## Setup

1. Python 3.11+
2. pip install -r requirements.txt
3. .env ausfüllen
4. python main.py


## DB Backup

- Automatisch: Background-Backup alle `BACKUP_INTERVAL_SECONDS` (default 21600s / 6h)
- Failsafe Slash Command: `/backup_db` (nur Privileged Owner)
- Output-Datei: `backups/db_backup.sql` im Repository

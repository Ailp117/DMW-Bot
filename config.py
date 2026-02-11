import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Für instant Slash-Sync in deinem privaten Server:
# GitHub Secret: GUILD_ID = "123456789012345678"
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")

# Optional: Debug DB SQL Logs
DB_ECHO = os.getenv("DB_ECHO", "0") == "1"

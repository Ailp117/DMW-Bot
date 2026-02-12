import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Optional: for instant slash command updates in your private server
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")

DB_ECHO = os.getenv("DB_ECHO", "0") == "1"

ENABLE_MESSAGE_CONTENT_INTENT = os.getenv("ENABLE_MESSAGE_CONTENT_INTENT", "0") == "1"

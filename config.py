import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Optional: for instant slash command updates in your private server
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")

DB_ECHO = os.getenv("DB_ECHO", "0") == "1"

ENABLE_MESSAGE_CONTENT_INTENT = _env_bool("ENABLE_MESSAGE_CONTENT_INTENT", default=True)

# Discord channel for live operational logs
LOG_GUILD_ID = int(os.getenv("LOG_GUILD_ID", "1471638702316060836") or "0")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1471639446641315931") or "0")

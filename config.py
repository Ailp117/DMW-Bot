import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Optional: for instant slash-command sync (recommended for private single-guild bots)
# Set as env var / GitHub Secret: GUILD_ID=123456789012345678
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt (ENV).")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL fehlt (ENV).")

TEMP_DELETE_SECONDS = 30

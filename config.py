import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt (ENV).")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL fehlt (ENV).")

TEMP_DELETE_SECONDS = 30

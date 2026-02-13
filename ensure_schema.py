from sqlalchemy import inspect, text

from models import Base
from db import engine


def _ensure_user_levels_username_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {col["name"] for col in inspector.get_columns("user_levels")}
    if "username" not in columns:
        sync_conn.execute(text("ALTER TABLE user_levels ADD COLUMN username TEXT"))


def _ensure_raids_display_id_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {col["name"] for col in inspector.get_columns("raids")}
    if "display_id" not in columns:
        sync_conn.execute(text("ALTER TABLE raids ADD COLUMN display_id INTEGER"))

    sync_conn.execute(text("""
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY guild_id ORDER BY created_at, id) AS rn
            FROM raids
        )
        UPDATE raids
        SET display_id = numbered.rn
        FROM numbered
        WHERE raids.id = numbered.id
          AND raids.display_id IS NULL
    """))

    sync_conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_raids_guild_display_id_unique
        ON raids (guild_id, display_id)
    """))


async def ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_user_levels_username_column)
        await conn.run_sync(_ensure_raids_display_id_column)

from sqlalchemy import inspect, text

from models import Base
from db import engine


def _ensure_user_levels_username_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {col["name"] for col in inspector.get_columns("user_levels")}
    if "username" not in columns:
        sync_conn.execute(text("ALTER TABLE user_levels ADD COLUMN username TEXT"))




def _ensure_guild_settings_name_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {col["name"] for col in inspector.get_columns("guild_settings")}
    if "guild_name" not in columns:
        sync_conn.execute(text("ALTER TABLE guild_settings ADD COLUMN guild_name TEXT"))
    if "default_min_players" not in columns:
        sync_conn.execute(text("ALTER TABLE guild_settings ADD COLUMN default_min_players INTEGER NOT NULL DEFAULT 0"))
    if "templates_enabled" not in columns:
        sync_conn.execute(text("ALTER TABLE guild_settings ADD COLUMN templates_enabled BOOLEAN NOT NULL DEFAULT TRUE"))
    if "template_manager_role_id" not in columns:
        sync_conn.execute(text("ALTER TABLE guild_settings ADD COLUMN template_manager_role_id BIGINT"))

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


def _ensure_raid_templates_constraints(sync_conn) -> None:
    sync_conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_raid_templates_guild_dungeon_name
        ON raid_templates (guild_id, dungeon_id, template_name)
    """))


def _ensure_raid_attendance_constraints(sync_conn) -> None:
    sync_conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_raid_attendance_unique_user
        ON raid_attendance (guild_id, raid_display_id, user_id)
    """))


async def ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_user_levels_username_column)
        await conn.run_sync(_ensure_guild_settings_name_column)
        await conn.run_sync(_ensure_raids_display_id_column)
        await conn.run_sync(_ensure_raid_templates_constraints)
        await conn.run_sync(_ensure_raid_attendance_constraints)

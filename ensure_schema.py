from sqlalchemy import inspect, text

from models import Base
from db import engine


def _ensure_user_levels_username_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {col["name"] for col in inspector.get_columns("user_levels")}
    if "username" not in columns:
        sync_conn.execute(text("ALTER TABLE user_levels ADD COLUMN username TEXT"))


async def ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_user_levels_username_column)

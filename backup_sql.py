from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from db import engine
from models import Base

BACKUP_DIR = Path("backups")
BACKUP_FILE = BACKUP_DIR / "db_backup.sql"
_BACKUP_WRITE_LOCK = asyncio.Lock()


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return "'" + value.isoformat().replace("'", "''") + "'"
    text_value = str(value)
    return "'" + text_value.replace("'", "''") + "'"


async def export_database_to_sql(output_path: Path = BACKUP_FILE) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with _BACKUP_WRITE_LOCK:
        lines: list[str] = [
            "-- DMW Bot SQL Backup",
            f"-- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
            "BEGIN;",
            "",
        ]

        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                lines.append(f'DELETE FROM "{table.name}";')
            lines.append("")

            for table in Base.metadata.sorted_tables:
                col_names = [col.name for col in table.columns]
                if not col_names:
                    continue

                result = await conn.execute(text(f'SELECT * FROM "{table.name}"'))
                rows = result.mappings().all()
                if not rows:
                    continue

                cols_sql = ", ".join(f'"{name}"' for name in col_names)
                for row in rows:
                    values_sql = ", ".join(_sql_literal(row[name]) for name in col_names)
                    lines.append(f'INSERT INTO "{table.name}" ({cols_sql}) VALUES ({values_sql});')
                lines.append("")

        lines.append("COMMIT;")

        temp_path = output_path.with_name(f".{output_path.name}.tmp")
        temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp_path.replace(output_path)
        return output_path

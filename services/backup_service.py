from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping
from utils.time_utils import berlin_now


_BACKUP_WRITE_LOCK = asyncio.Lock()
_PREFERRED_INSERT_ORDER = (
    "guild_settings",
    "dungeons",
    "raids",
    "raid_options",
    "raid_votes",
    "raid_posted_slots",
    "raid_templates",
    "raid_attendance",
    "user_levels",
    "debug_mirror_cache",
)


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return "'" + current.isoformat().replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _ordered_table_names(rows_by_table: Mapping[str, Iterable[Mapping[str, object]]]) -> tuple[list[str], list[str]]:
    table_names = [table_name for table_name, _ in rows_by_table.items()]
    available = set(table_names)
    preferred = [name for name in _PREFERRED_INSERT_ORDER if name in available]
    extras = sorted(name for name in available if name not in set(_PREFERRED_INSERT_ORDER))

    insert_order = preferred + extras
    delete_order = list(reversed(insert_order))
    return delete_order, insert_order


async def export_rows_to_sql(
    output_path: Path,
    *,
    rows_by_table: Mapping[str, Iterable[Mapping[str, object]]],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    delete_order, insert_order = _ordered_table_names(rows_by_table)

    async with _BACKUP_WRITE_LOCK:
        lines = [
            "-- DMW Rewrite SQL Backup",
            f"-- generated_at_berlin: {berlin_now().isoformat()}",
            "BEGIN;",
            "",
        ]

        for table_name in delete_order:
            lines.append(f'DELETE FROM "{table_name}";')
        lines.append("")

        for table_name in insert_order:
            rows = rows_by_table[table_name]
            row_list = list(rows)
            if not row_list:
                continue
            columns = list(row_list[0].keys())
            column_sql = ", ".join(f'"{name}"' for name in columns)
            for row in row_list:
                values_sql = ", ".join(sql_literal(row[col]) for col in columns)
                lines.append(f'INSERT INTO "{table_name}" ({column_sql}) VALUES ({values_sql});')
            lines.append("")

        lines.append("COMMIT;")

        temp_path = output_path.with_name(f".{output_path.name}.tmp")
        temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp_path.replace(output_path)
        return output_path

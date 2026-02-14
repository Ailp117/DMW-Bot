from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services.backup_service import export_rows_to_sql


@pytest.mark.asyncio
async def test_backup_export_lock_and_atomic_replace(tmp_path: Path):
    out = tmp_path / "db_backup.sql"

    rows = {
        "guild_settings": [
            {"guild_id": 1, "guild_name": "Guild", "templates_enabled": True},
        ],
        "raids": [
            {"id": 1, "guild_id": 1, "dungeon": "Nanos"},
        ],
    }

    await asyncio.gather(
        export_rows_to_sql(out, rows_by_table=rows),
        export_rows_to_sql(out, rows_by_table=rows),
    )

    text = out.read_text(encoding="utf-8")
    assert "BEGIN;" in text
    assert "COMMIT;" in text
    assert "INSERT INTO \"guild_settings\"" in text
    assert not (tmp_path / ".db_backup.sql.tmp").exists()


@pytest.mark.asyncio
async def test_backup_command_failure_path(tmp_path: Path):
    out = tmp_path / "db_backup.sql"

    class _BadRows:
        def __iter__(self):
            return iter(())

        def items(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await export_rows_to_sql(out, rows_by_table=_BadRows())


@pytest.mark.asyncio
async def test_backup_export_uses_fk_safe_table_order(tmp_path: Path):
    out = tmp_path / "db_backup.sql"
    rows = {
        "raid_votes": [{"id": 1, "raid_id": 5, "kind": "day", "option_label": "Fri", "user_id": 42}],
        "raids": [{"id": 5, "guild_id": 1, "channel_id": 1, "creator_id": 2, "dungeon": "Nanos"}],
        "guild_settings": [{"guild_id": 1}],
        "dungeons": [{"id": 2, "name": "Nanos", "short_code": "NAN"}],
        "raid_options": [{"id": 9, "raid_id": 5, "kind": "day", "label": "Fri"}],
        "raid_templates": [{"id": 3, "guild_id": 1, "dungeon_id": 2, "template_name": "auto", "template_data": "{}"}],
    }

    await export_rows_to_sql(out, rows_by_table=rows)
    text = out.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    delete_votes = lines.index('DELETE FROM "raid_votes";')
    delete_options = lines.index('DELETE FROM "raid_options";')
    delete_templates = lines.index('DELETE FROM "raid_templates";')
    delete_raids = lines.index('DELETE FROM "raids";')
    delete_guild = lines.index('DELETE FROM "guild_settings";')
    delete_dungeons = lines.index('DELETE FROM "dungeons";')

    assert delete_votes < delete_raids
    assert delete_options < delete_raids
    assert delete_templates < delete_guild
    assert delete_templates < delete_dungeons

    insert_guild = lines.index('INSERT INTO "guild_settings" ("guild_id") VALUES (1);')
    insert_dungeons = lines.index('INSERT INTO "dungeons" ("id", "name", "short_code") VALUES (2, \'Nanos\', \'NAN\');')
    insert_raids = lines.index(
        'INSERT INTO "raids" ("id", "guild_id", "channel_id", "creator_id", "dungeon") VALUES (5, 1, 1, 2, \'Nanos\');'
    )
    insert_options = lines.index(
        'INSERT INTO "raid_options" ("id", "raid_id", "kind", "label") VALUES (9, 5, \'day\', \'Fri\');'
    )
    insert_votes = lines.index(
        'INSERT INTO "raid_votes" ("id", "raid_id", "kind", "option_label", "user_id") VALUES (1, 5, \'day\', \'Fri\', 42);'
    )
    insert_templates = lines.index(
        'INSERT INTO "raid_templates" ("id", "guild_id", "dungeon_id", "template_name", "template_data") VALUES (3, 1, 2, \'auto\', \'{}\');'
    )

    assert insert_guild < insert_raids
    assert insert_dungeons < insert_raids
    assert insert_raids < insert_options
    assert insert_options < insert_votes
    assert insert_guild < insert_templates
    assert insert_dungeons < insert_templates

from __future__ import annotations

import pytest

from db.models import Base, REQUIRED_BOOT_TABLES, mapped_public_table_names
from db.schema_guard import _required_model_columns, ensure_required_schema, validate_required_tables


class DummyConnection:
    def __init__(self) -> None:
        self.ddl: list[str] = []
        self.run_sync_calls = 0

    async def execute(self, clause):
        self.ddl.append(str(clause))
        return None

    async def run_sync(self, fn):
        self.run_sync_calls += 1
        return None


def test_required_boot_tables_cover_all_mapped_tables():
    mapped_tables = set(Base.metadata.tables.keys())
    required_tables = set(REQUIRED_BOOT_TABLES)

    assert required_tables == mapped_tables


def test_mapped_public_table_names_matches_required_boot_tables():
    assert tuple(REQUIRED_BOOT_TABLES) == tuple(mapped_public_table_names())


@pytest.mark.asyncio
async def test_validate_required_tables_detects_missing_table(monkeypatch):
    async def fake_tables(_connection):
        return {"guild_settings"}

    async def fake_columns(_connection):
        return {}

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)

    with pytest.raises(RuntimeError, match="Missing required DB tables"):
        await validate_required_tables(connection=None)


@pytest.mark.asyncio
async def test_validate_required_tables_detects_missing_columns(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)

    async def fake_tables(_connection):
        return set(required)

    async def fake_columns(_connection):
        out = {table: set(columns) for table, columns in expected_columns.items()}
        out["raids"].remove("display_id")
        return out

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)

    with pytest.raises(RuntimeError, match="Missing required DB columns"):
        await validate_required_tables(connection=None)


@pytest.mark.asyncio
async def test_validate_required_tables_passes_for_complete_schema(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)

    async def fake_tables(_connection):
        return set(required)

    async def fake_columns(_connection):
        return {table: set(columns) for table, columns in expected_columns.items()}

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)

    await validate_required_tables(connection=None)


@pytest.mark.asyncio
async def test_ensure_required_schema_applies_missing_table_and_column(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)

    async def fake_tables(_connection):
        # Simulate a partially missing schema where most required tables are absent.
        return {"guild_settings"}

    async def fake_columns(_connection):
        out = {table: set(columns) for table, columns in expected_columns.items()}
        out["raids"].remove("display_id")
        return out

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)

    connection = DummyConnection()
    changes = await ensure_required_schema(connection=connection)

    assert connection.run_sync_calls == 1
    assert any(change.startswith("create_table:") for change in changes)
    assert "add_column:raids.display_id" in changes
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS ix_raids_guild_display_id_unique" in ddl for ddl in connection.ddl)


@pytest.mark.asyncio
async def test_ensure_required_schema_no_structural_change_when_complete(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)

    async def fake_tables(_connection):
        return set(required)

    async def fake_columns(_connection):
        return {table: set(columns) for table, columns in expected_columns.items()}

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)

    connection = DummyConnection()
    changes = await ensure_required_schema(connection=connection)

    assert connection.run_sync_calls == 0
    assert changes == []

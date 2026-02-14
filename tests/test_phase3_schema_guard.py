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

    async def fake_column_types(_connection):
        return {}

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

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

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int8",
            ("user_levels", "level"): "int8",
        }

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

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

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int8",
            ("user_levels", "level"): "int8",
        }

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

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

    async def fake_rls(_connection):
        return set()

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int8",
            ("user_levels", "level"): "int8",
        }

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_rls_enabled_tables", fake_rls)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

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

    async def fake_rls(_connection):
        return set(required)

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int8",
            ("user_levels", "level"): "int8",
        }

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_rls_enabled_tables", fake_rls)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

    connection = DummyConnection()
    changes = await ensure_required_schema(connection=connection)

    assert connection.run_sync_calls == 0
    assert changes == []


@pytest.mark.asyncio
async def test_ensure_required_schema_enables_rls_when_missing(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)
    already_enabled = {"raids"}

    async def fake_tables(_connection):
        return set(required)

    async def fake_columns(_connection):
        return {table: set(columns) for table, columns in expected_columns.items()}

    async def fake_rls(_connection):
        return set(already_enabled)

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int8",
            ("user_levels", "level"): "int8",
        }

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_rls_enabled_tables", fake_rls)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

    connection = DummyConnection()
    changes = await ensure_required_schema(connection=connection)

    assert connection.run_sync_calls == 0
    for table in required:
        if table in already_enabled:
            continue
        assert f"enable_rls:{table}" in changes
        assert any(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY' in ddl for ddl in connection.ddl)


@pytest.mark.asyncio
async def test_validate_required_tables_detects_invalid_user_level_column_type(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)

    async def fake_tables(_connection):
        return set(required)

    async def fake_columns(_connection):
        return {table: set(columns) for table, columns in expected_columns.items()}

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int4",
            ("user_levels", "level"): "int8",
        }

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)

    with pytest.raises(RuntimeError, match="Invalid required DB column types"):
        await validate_required_tables(connection=None)


@pytest.mark.asyncio
async def test_ensure_required_schema_migrates_user_level_columns_to_bigint(monkeypatch):
    required = list(REQUIRED_BOOT_TABLES)
    expected_columns = _required_model_columns(required)

    async def fake_tables(_connection):
        return set(required)

    async def fake_columns(_connection):
        return {table: set(columns) for table, columns in expected_columns.items()}

    async def fake_column_types(_connection):
        return {
            ("user_levels", "xp"): "int4",
            ("user_levels", "level"): "int4",
        }

    async def fake_rls(_connection):
        return set(required)

    monkeypatch.setattr("db.schema_guard.fetch_public_tables", fake_tables)
    monkeypatch.setattr("db.schema_guard.fetch_public_columns", fake_columns)
    monkeypatch.setattr("db.schema_guard.fetch_public_column_udt_names", fake_column_types)
    monkeypatch.setattr("db.schema_guard.fetch_public_rls_enabled_tables", fake_rls)

    connection = DummyConnection()
    changes = await ensure_required_schema(connection=connection)

    assert "alter_column_type:user_levels.xp:bigint" in changes
    assert "alter_column_type:user_levels.level:bigint" in changes
    assert any(
        'ALTER TABLE public."user_levels" ALTER COLUMN "xp" TYPE BIGINT USING "xp"::BIGINT' in ddl
        for ddl in connection.ddl
    )
    assert any(
        'ALTER TABLE public."user_levels" ALTER COLUMN "level" TYPE BIGINT USING "level"::BIGINT' in ddl
        for ddl in connection.ddl
    )

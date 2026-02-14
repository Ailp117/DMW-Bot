from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import Table, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection

from db.models import Base, mapped_public_table_names


CRITICAL_INDEX_DDLS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_raids_guild_display_id_unique ON public.raids (guild_id, display_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_raid_attendance_unique_user ON public.raid_attendance (guild_id, raid_display_id, user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_raid_votes_unique ON public.raid_votes (raid_id, kind, option_label, user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_raid_options_raid_kind_label ON public.raid_options (raid_id, kind, label)",
)
BIGINT_COLUMN_UDT_NAMES = frozenset({"int8", "bigint"})
REQUIRED_BIGINT_COLUMNS = (
    ("user_levels", "xp"),
    ("user_levels", "level"),
)


async def fetch_public_tables(connection: AsyncConnection) -> set[str]:
    result = await connection.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    return set(result.scalars().all())


async def fetch_public_columns(connection: AsyncConnection) -> dict[str, set[str]]:
    result = await connection.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            """
        )
    )
    rows = result.fetchall()
    columns_by_table: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        columns_by_table.setdefault(table_name, set()).add(column_name)
    return columns_by_table


async def fetch_public_column_udt_names(connection: AsyncConnection) -> dict[tuple[str, str], str]:
    result = await connection.execute(
        text(
            """
            SELECT table_name, column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            """
        )
    )
    rows = result.fetchall()
    udt_names_by_column: dict[tuple[str, str], str] = {}
    for table_name, column_name, udt_name in rows:
        udt_names_by_column[(str(table_name), str(column_name))] = str(udt_name or "").lower()
    return udt_names_by_column


async def fetch_public_rls_enabled_tables(connection: AsyncConnection) -> set[str]:
    result = await connection.execute(
        text(
            """
            SELECT cls.relname
            FROM pg_class AS cls
            JOIN pg_namespace AS ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = 'public'
              AND cls.relkind = 'r'
              AND cls.relrowsecurity = true
            """
        )
    )
    return set(result.scalars().all())


def _model_table_map() -> dict[str, Table]:
    return {table.name: table for table in Base.metadata.sorted_tables}


def _required_model_columns(required_tables: Iterable[str]) -> dict[str, set[str]]:
    mapped = {table.name: {column.name for column in table.columns} for table in Base.metadata.sorted_tables}
    required_list = list(required_tables)
    unknown = sorted(table for table in required_list if table not in mapped)
    if unknown:
        raise RuntimeError(f"Schema guard references unmapped tables: {', '.join(unknown)}")
    return {table: mapped[table] for table in required_list}


def _resolve_required_tables(required_tables: Iterable[str] | None) -> list[str]:
    if required_tables is None:
        return list(mapped_public_table_names())
    return list(required_tables)


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text_value = str(value).replace("'", "''")
    return f"'{text_value}'"


def _column_default_sql(column: Any) -> str | None:
    if column.server_default is not None and column.server_default.arg is not None:
        arg = column.server_default.arg
        if hasattr(arg, "compile"):
            return str(
                arg.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        return str(arg)

    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        return _sql_literal(default.arg)

    return None


def _build_add_column_sql(table_name: str, column: Any) -> str:
    type_sql = column.type.compile(dialect=postgresql.dialect())
    default_sql = _column_default_sql(column)

    default_clause = f" DEFAULT {default_sql}" if default_sql is not None else ""
    # If a column is NOT NULL but has no usable default, add it nullable first.
    # This keeps migrations resilient for existing rows; application logic still validates data.
    not_null_clause = " NOT NULL" if (not column.nullable and default_sql is not None) else ""

    return (
        f'ALTER TABLE public."{table_name}" '
        f'ADD COLUMN IF NOT EXISTS "{column.name}" {type_sql}{default_clause}{not_null_clause}'
    )


def _build_alter_column_bigint_sql(table_name: str, column_name: str) -> str:
    return (
        f'ALTER TABLE public."{table_name}" '
        f'ALTER COLUMN "{column_name}" TYPE BIGINT USING "{column_name}"::BIGINT'
    )


async def ensure_required_schema(
    connection: AsyncConnection,
    required_tables: Iterable[str] | None = None,
) -> list[str]:
    required_list = _resolve_required_tables(required_tables)
    table_map = _model_table_map()
    missing_mapped = sorted(table for table in required_list if table not in table_map)
    if missing_mapped:
        raise RuntimeError(f"Schema guard references unmapped tables: {', '.join(missing_mapped)}")

    changes: list[str] = []

    existing_tables = await fetch_public_tables(connection)
    missing_tables = [table for table in required_list if table not in existing_tables]
    if missing_tables:
        create_tables: list[Table] = [table_map[name] for name in missing_tables]

        def _sync_create(sync_connection):
            Base.metadata.create_all(sync_connection, tables=create_tables, checkfirst=True)

        await connection.run_sync(_sync_create)
        changes.extend([f"create_table:{name}" for name in missing_tables])

    existing_columns = await fetch_public_columns(connection)
    for table_name in required_list:
        expected_table = table_map[table_name]
        known_columns = existing_columns.get(table_name, set())
        for column in expected_table.columns:
            if column.name in known_columns:
                continue
            ddl = _build_add_column_sql(table_name, column)
            await connection.execute(text(ddl))
            changes.append(f"add_column:{table_name}.{column.name}")
            known_columns.add(column.name)
        existing_columns[table_name] = known_columns

    column_udt_names = await fetch_public_column_udt_names(connection)
    for table_name, column_name in REQUIRED_BIGINT_COLUMNS:
        if table_name not in required_list:
            continue
        udt_name = column_udt_names.get((table_name, column_name))
        if udt_name in BIGINT_COLUMN_UDT_NAMES:
            continue
        if udt_name is None:
            continue
        ddl = _build_alter_column_bigint_sql(table_name, column_name)
        await connection.execute(text(ddl))
        changes.append(f"alter_column_type:{table_name}.{column_name}:bigint")

    for ddl in CRITICAL_INDEX_DDLS:
        await connection.execute(text(ddl))

    rls_enabled_tables = await fetch_public_rls_enabled_tables(connection)
    for table_name in required_list:
        if table_name in rls_enabled_tables:
            continue
        await connection.execute(text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'))
        changes.append(f"enable_rls:{table_name}")

    return changes


async def validate_required_tables(connection: AsyncConnection, required_tables: Iterable[str] | None = None) -> None:
    required_list = _resolve_required_tables(required_tables)

    existing = await fetch_public_tables(connection)
    missing = sorted([table for table in required_list if table not in existing])
    if missing:
        raise RuntimeError(f"Missing required DB tables: {', '.join(missing)}")

    expected_columns = _required_model_columns(required_list)
    existing_columns = await fetch_public_columns(connection)
    missing_columns: list[str] = []
    for table in required_list:
        missing_for_table = sorted(expected_columns[table] - existing_columns.get(table, set()))
        if missing_for_table:
            missing_columns.append(f"{table}({', '.join(missing_for_table)})")

    if missing_columns:
        raise RuntimeError(f"Missing required DB columns: {'; '.join(missing_columns)}")

    udt_names = await fetch_public_column_udt_names(connection)
    invalid_types: list[str] = []
    for table_name, column_name in REQUIRED_BIGINT_COLUMNS:
        if table_name not in required_list:
            continue
        udt_name = udt_names.get((table_name, column_name))
        if udt_name is None:
            continue
        if udt_name not in BIGINT_COLUMN_UDT_NAMES:
            invalid_types.append(f"{table_name}.{column_name}={udt_name}")
    if invalid_types:
        raise RuntimeError(f"Invalid required DB column types: {', '.join(invalid_types)}")

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.sql.dml import Delete, Insert, Update

from services.persistence_service import RepositoryPersistence


def _update_value_keys(statement: object) -> set[str]:
    keys: set[str] = set()
    values = getattr(statement, "_values", {})
    for key in values:
        key_name = getattr(key, "key", None)
        if isinstance(key_name, str):
            keys.add(key_name)
            continue
        if isinstance(key, str):
            keys.add(key)
            continue
        keys.add(str(key))
    return keys


class _DummySession:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.add_all_calls = 0
        self.executed_statements: list[object] = []
        self.executed_params: list[object | None] = []
        self.added_rows: list[object] = []

    async def execute(self, stmt, params=None):
        self.execute_calls += 1
        self.executed_statements.append(stmt)
        self.executed_params.append(params)

    def add_all(self, rows):
        self.add_all_calls += 1
        self.added_rows.extend(list(rows))


class _DummySessionManager:
    def __init__(self) -> None:
        self.session_scope_calls = 0
        self.sessions: list[_DummySession] = []

    @asynccontextmanager
    async def session_scope(self):
        self.session_scope_calls += 1
        session = _DummySession()
        self.sessions.append(session)
        yield session


def _is_insert_statement_for_table(statement: object, table_name: str) -> bool:
    return isinstance(statement, Insert) and getattr(getattr(statement, "table", None), "name", None) == table_name


@pytest.mark.asyncio
async def test_flush_skips_db_when_repository_state_is_unchanged(config, repo):
    persistence = RepositoryPersistence(config)
    dummy_manager = _DummySessionManager()
    persistence.session_manager = dummy_manager

    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1
    assert any(
        _is_insert_statement_for_table(stmt, "dungeons")
        for stmt in dummy_manager.sessions[0].executed_statements
    )

    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1

    repo.ensure_settings(1, "Guild")
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 2
    assert any(
        _is_insert_statement_for_table(stmt, "guild_settings")
        for stmt in dummy_manager.sessions[1].executed_statements
    )


@pytest.mark.asyncio
async def test_flush_uses_update_for_changed_existing_row(config, repo):
    persistence = RepositoryPersistence(config)
    dummy_manager = _DummySessionManager()
    persistence.session_manager = dummy_manager

    repo.ensure_settings(1, "Guild")
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1

    repo.ensure_settings(1, "Guild-Updated")
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 2

    statements = dummy_manager.sessions[1].executed_statements
    assert any(
        isinstance(stmt, Update) and getattr(getattr(stmt, "table", None), "name", None) == "guild_settings"
        for stmt in statements
    )
    assert not any(
        isinstance(stmt, Delete) and getattr(getattr(stmt, "table", None), "name", None) == "guild_settings"
        for stmt in statements
    )
    guild_updates = [
        stmt
        for stmt in statements
        if isinstance(stmt, Update) and getattr(getattr(stmt, "table", None), "name", None) == "guild_settings"
    ]
    assert guild_updates
    assert _update_value_keys(guild_updates[-1]) == {"guild_name"}


@pytest.mark.asyncio
async def test_flush_deletes_only_changed_table_rows(config, repo):
    persistence = RepositoryPersistence(config)
    dummy_manager = _DummySessionManager()
    persistence.session_manager = dummy_manager

    repo.ensure_settings(1, "Guild")
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1

    repo.settings.clear()
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 2

    statements = dummy_manager.sessions[1].executed_statements
    assert any(
        isinstance(stmt, Delete) and getattr(getattr(stmt, "table", None), "name", None) == "guild_settings"
        for stmt in statements
    )
    assert not any(
        isinstance(stmt, Delete) and getattr(getattr(stmt, "table", None), "name", None) == "dungeons"
        for stmt in statements
    )


@pytest.mark.asyncio
async def test_flush_uses_dirty_table_hints_for_snapshot_scope(config, repo):
    persistence = RepositoryPersistence(config)
    dummy_manager = _DummySessionManager()
    persistence.session_manager = dummy_manager
    captured_table_sets: list[set[str]] = []

    original_snapshot = persistence._snapshot_rows_for_tables

    def _capture_snapshot(repo_arg, table_names):
        captured_table_sets.append(set(table_names))
        return original_snapshot(repo_arg, table_names)

    persistence._snapshot_rows_for_tables = _capture_snapshot  # type: ignore[method-assign]

    await persistence.flush(repo)
    repo.get_or_create_user_level(1, 42, "User42").xp = 5
    await persistence.flush(repo, dirty_tables={"user_levels"})

    assert captured_table_sets
    assert "user_levels" in captured_table_sets[-1]
    assert "settings" not in captured_table_sets[-1]


@pytest.mark.asyncio
async def test_flush_batches_updates_by_column_set(config, repo):
    persistence = RepositoryPersistence(config)
    dummy_manager = _DummySessionManager()
    persistence.session_manager = dummy_manager

    repo.get_or_create_user_level(1, 10, "User10").xp = 1
    repo.get_or_create_user_level(1, 11, "User11").xp = 2
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1

    repo.get_or_create_user_level(1, 10, "User10").xp = 3
    repo.get_or_create_user_level(1, 11, "User11").xp = 4
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 2

    second_session = dummy_manager.sessions[1]
    level_updates = [
        (stmt, params)
        for stmt, params in zip(second_session.executed_statements, second_session.executed_params)
        if isinstance(stmt, Update) and getattr(getattr(stmt, "table", None), "name", None) == "user_levels"
    ]
    assert level_updates
    assert len(level_updates) == 1
    _, params = level_updates[0]
    assert isinstance(params, list)
    assert len(params) == 2
    assert all("xp" in row and "pk_guild_id" in row and "pk_user_id" in row for row in params)
    statement, _ = level_updates[0]
    execution_options = dict(getattr(statement, "_execution_options", {}))
    assert execution_options.get("synchronize_session") is False

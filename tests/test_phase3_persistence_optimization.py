from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from services.persistence_service import RepositoryPersistence


class _DummySession:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.add_all_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1

    def add_all(self, _rows):
        self.add_all_calls += 1


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


@pytest.mark.asyncio
async def test_flush_skips_db_when_repository_state_is_unchanged(config, repo):
    persistence = RepositoryPersistence(config)
    dummy_manager = _DummySessionManager()
    persistence.session_manager = dummy_manager

    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1
    assert dummy_manager.sessions[0].execute_calls > 0

    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 1

    repo.ensure_settings(1, "Guild")
    await persistence.flush(repo)
    assert dummy_manager.session_scope_calls == 2
    assert dummy_manager.sessions[1].execute_calls > 0

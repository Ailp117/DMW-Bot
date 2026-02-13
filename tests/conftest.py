from __future__ import annotations

import pytest

from bot.config import BotConfig
from bot.main import BotApplication
from db.repository import InMemoryRepository


@pytest.fixture
def config() -> BotConfig:
    return BotConfig(
        discord_token="token",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/db",
        db_echo=False,
        enable_message_content_intent=True,
        log_guild_id=0,
        log_channel_id=0,
        self_test_interval_seconds=900,
        backup_interval_seconds=21600,
        raidlist_debug_channel_id=0,
        memberlist_debug_channel_id=0,
        discord_log_level="DEBUG",
    )


@pytest.fixture
def repo() -> InMemoryRepository:
    store = InMemoryRepository()
    store.add_dungeon(name="Nanos", short_code="NAN", sort_order=1)
    store.add_dungeon(name="Skull", short_code="SKL", sort_order=2)
    return store


@pytest.fixture
def app(config: BotConfig, repo: InMemoryRepository) -> BotApplication:
    return BotApplication(config=config, repo=repo)

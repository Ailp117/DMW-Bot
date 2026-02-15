from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import logging
import os
import time

from bot.config import load_config
from bot.discord_api import app_commands, discord
from bot.logging import setup_logging
from db.repository import InMemoryRepository
from features.runtime_mixins import (
    RuntimeEventsMixin,
    RuntimeLoggingBackgroundMixin,
    RuntimeRaidOpsMixin,
    RuntimeStateCalendarMixin,
)
from services.leveling_service import LevelingService
from services.persistence_service import RepositoryPersistence
from discord.task_registry import DebouncedGuildUpdater, SingletonTaskRegistry
from utils.runtime_helpers import *  # noqa: F401,F403


class RewriteDiscordBot(
    RuntimeEventsMixin,
    RuntimeLoggingBackgroundMixin,
    RuntimeStateCalendarMixin,
    RuntimeRaidOpsMixin,
    discord.Client,
):
    def __init__(self, repo: InMemoryRepository, config) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = config.enable_message_content_intent
        discord.Client.__init__(self, intents=intents)

        self.repo = repo
        self.config = config
        self.persistence = RepositoryPersistence(config)
        self.tree = app_commands.CommandTree(self)
        self.task_registry = SingletonTaskRegistry()
        self.raidlist_updater = DebouncedGuildUpdater(
            self._refresh_raidlist_for_guild_persisted,
            debounce_seconds=1.5,
            cooldown_seconds=0.8,
        )
        self.leveling_service = LevelingService()

        self.log_channel = None
        self.log_forward_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=LOG_FORWARD_QUEUE_MAX_SIZE)
        self.pending_log_buffer: deque[str] = deque(maxlen=250)
        self.log_forwarder_active = False
        self.last_self_test_ok_at: datetime | None = None
        self.last_self_test_error: str | None = None

        self._commands_registered = False
        self._state_loaded = False
        self._views_restored = False
        self._commands_synced = False
        self._runtime_restored = False
        self._slash_command_names: set[str] = set()

        self._ack_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._application_owner_ids: set[int] = set()
        self._guild_feature_settings: dict[int, GuildFeatureSettings] = {}
        self._acked_interactions: set[int] = set()
        self._raidlist_hash_by_guild: dict[int, str] = {}
        self._username_sync_next_run_by_guild: dict[int, float] = {}
        self._level_state_dirty = False
        self._last_level_persist_monotonic = time.monotonic()
        self._discord_log_handler = self._build_discord_log_handler()
        self._discord_loggers: list[logging.Logger] = []
        self._attach_discord_log_handler()

    def _register_commands(self) -> None:
        from commands.runtime_commands import register_runtime_commands

        register_runtime_commands(self)

    async def close(self) -> None:
        try:
            async with self._state_lock:
                await self._flush_level_state_if_due(force=True)
        except Exception:
            log.exception("Failed to flush pending level state during shutdown.")
        try:
            await self.task_registry.cancel_all()
        except Exception:
            log.exception("Failed to cancel background tasks during shutdown.")
        try:
            for logger in self._discord_loggers:
                logger.removeHandler(self._discord_log_handler)
        except Exception:
            log.exception("Failed to detach Discord log handler during shutdown.")
        await super().close()


def run() -> int:
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    try:
        config = load_config()
    except ValueError as exc:
        log.error("Config error: %s", exc)
        return 1

    setup_logging(config.discord_log_level)
    if not config.discord_token:
        log.error("DISCORD_TOKEN missing")
        return 1

    repo = InMemoryRepository()
    bot = RewriteDiscordBot(repo=repo, config=config)

    try:
        bot.run(config.discord_token)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

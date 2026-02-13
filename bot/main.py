from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from bot.config import BotConfig
from discord.task_registry import DebouncedGuildUpdater, SingletonTaskRegistry
from features.background import BACKGROUND_LOOP_NAMES
from features.commands import registered_command_names
from services.admin_service import cancel_all_open_raids
from services.leveling_service import LevelingService
from services.raid_service import cleanup_stale_raids, restore_memberlists, restore_persistent_views
from services.raidlist_service import RaidlistHashCache, render_raidlist
from services.startup_service import (
    EXPECTED_SLASH_COMMANDS,
    BootSmokeStats,
    SingletonGate,
    command_registry_health,
    run_boot_smoke_checks,
)
from utils.text import contains_approved_keyword, contains_nanomon_keyword
from db.repository import InMemoryRepository
from db.models import REQUIRED_BOOT_TABLES


NANOMON_IMAGE_URL = "https://wikimon.net/images/thumb/c/cc/Nanomon_New_Century.png/200px-Nanomon_New_Century.png"
APPROVED_GIF_URL = "https://c.tenor.com/l8waltLHrxcAAAAC/tenor.gif"


@dataclass(slots=True)
class SelfTestState:
    last_ok_at: datetime | None = None
    last_error: str | None = None


class BotApplication:
    def __init__(
        self,
        *,
        config: BotConfig,
        repo: InMemoryRepository,
        singleton_gate: SingletonGate | None = None,
    ) -> None:
        self.config = config
        self.repo = repo
        self.singleton_gate = singleton_gate or SingletonGate()

        self.task_registry = SingletonTaskRegistry()
        self.leveling_service = LevelingService()
        self.raidlist_hash_cache = RaidlistHashCache()

        self.raidlist_updater = DebouncedGuildUpdater(self._refresh_raidlist_for_guild)

        self.boot_smoke_stats: BootSmokeStats | None = None
        self.self_test_state = SelfTestState()
        self.log_forward_queue: asyncio.Queue[str] = asyncio.Queue()
        self.pending_log_buffer: list[str] = []
        self.log_forwarder_active = False

        self._ready_sync_done = False
        self._initial_raidlist_refresh_done = False
        self._initial_memberlist_restore_done = False
        self._startup_cleanup_done = False

    @property
    def expected_commands(self) -> set[str]:
        return set(EXPECTED_SLASH_COMMANDS)

    @property
    def registered_commands(self) -> list[str]:
        return registered_command_names()

    def command_registry_health(self) -> tuple[list[str], list[str], list[str]]:
        return command_registry_health(self.registered_commands)

    def run_boot_smoke_checks(self, *, existing_tables: Iterable[str]) -> BootSmokeStats:
        return run_boot_smoke_checks(self.repo, existing_tables)

    async def setup(self, *, existing_tables: Iterable[str] = REQUIRED_BOOT_TABLES) -> None:
        if not await self.singleton_gate.try_acquire():
            raise SystemExit(0)

        self.boot_smoke_stats = self.run_boot_smoke_checks(existing_tables=existing_tables)
        await self.restore_runtime_state()
        self._start_background_loops()

    async def restore_runtime_state(self) -> None:
        restore_persistent_views(self.repo)
        restore_memberlists(self.repo)

    def _start_background_loops(self) -> None:
        for loop_name in BACKGROUND_LOOP_NAMES:
            self.task_registry.start_once(loop_name, lambda name=loop_name: self._background_worker(name))

    async def _background_worker(self, name: str) -> None:
        while True:
            await asyncio.sleep(3600)

    async def on_ready(self, *, connected_guild_ids: Iterable[int]) -> None:
        if not self._startup_cleanup_done:
            await self.cleanup_removed_guilds(connected_guild_ids=connected_guild_ids)
            self._startup_cleanup_done = True

        if not self._ready_sync_done:
            self.sync_commands_for_known_guilds(connected_guild_ids)
            self._ready_sync_done = True

        if not self._initial_raidlist_refresh_done:
            for guild_id in connected_guild_ids:
                await self._refresh_raidlist_for_guild(guild_id)
            self._initial_raidlist_refresh_done = True

        if not self._initial_memberlist_restore_done:
            restore_memberlists(self.repo)
            self._initial_memberlist_restore_done = True

        self.log_forwarder_active = True
        self.flush_pending_logs()

    def sync_commands_for_known_guilds(self, connected_guild_ids: Iterable[int]) -> tuple[list[int], bool]:
        known = {int(guild_id) for guild_id in connected_guild_ids}
        known.update(self.repo.settings.keys())
        synced = sorted(known)
        global_synced = True
        return synced, global_synced

    async def _refresh_raidlist_for_guild(self, guild_id: int) -> None:
        settings = self.repo.ensure_settings(guild_id)
        if not settings.raidlist_channel_id:
            return
        raids = self.repo.list_open_raids(guild_id)
        guild_name = settings.guild_name or f"Guild {guild_id}"
        render = render_raidlist(guild_id, guild_name, raids)
        if not self.raidlist_hash_cache.should_publish(render):
            return
        settings.raidlist_message_id = settings.raidlist_message_id or (guild_id * 1000 + 1)

    async def run_self_tests_once(self) -> None:
        _, missing, unexpected = self.command_registry_health()
        if missing:
            self.self_test_state.last_error = f"Missing commands: {', '.join(missing)}"
            raise RuntimeError(self.self_test_state.last_error)
        if unexpected:
            self.self_test_state.last_error = f"Unexpected commands: {', '.join(unexpected)}"
            raise RuntimeError(self.self_test_state.last_error)

        self.self_test_state.last_ok_at = datetime.now(UTC)
        self.self_test_state.last_error = None

    async def cleanup_removed_guilds(self, *, connected_guild_ids: Iterable[int]) -> None:
        connected = {int(guild_id) for guild_id in connected_guild_ids}
        known = set(self.repo.settings.keys()) | {raid.guild_id for raid in self.repo.raids.values()}
        removed = sorted(known - connected)
        for guild_id in removed:
            self.repo.purge_guild_data(guild_id)

    async def on_guild_remove(self, guild_id: int) -> dict[str, int]:
        return self.repo.purge_guild_data(guild_id)

    async def on_guild_join(self, guild_id: int, guild_name: str) -> None:
        self.repo.ensure_settings(guild_id, guild_name)
        await self._refresh_raidlist_for_guild(guild_id)

    def apply_message_xp(self, *, guild_id: int, user_id: int, username: str | None) -> int:
        result = self.leveling_service.update_message_xp(
            self.repo,
            guild_id=guild_id,
            user_id=user_id,
            username=username,
        )
        return result.current_level

    def message_keyword_replies(self, content: str) -> list[str]:
        replies: list[str] = []
        if contains_nanomon_keyword(content):
            replies.append(NANOMON_IMAGE_URL)
        if contains_approved_keyword(content):
            replies.append(APPROVED_GIF_URL)
        return replies

    async def cleanup_stale_raids_once(self, *, now: datetime, stale_hours: int = 7 * 24) -> tuple[int, list[int]]:
        result = cleanup_stale_raids(self.repo, now=now, stale_hours=stale_hours)
        for guild_id in result.affected_guild_ids:
            await self._refresh_raidlist_for_guild(guild_id)
        return result.cleaned_count, result.affected_guild_ids

    async def cancel_all_raids(self, guild_id: int) -> int:
        count = cancel_all_open_raids(self.repo, guild_id=guild_id)
        await self._refresh_raidlist_for_guild(guild_id)
        return count

    def enqueue_discord_log(self, message: str) -> None:
        if not message:
            return
        normalized = message if len(message) <= 1800 else f"{message[:1797]}..."
        if self.log_forwarder_active:
            self.log_forward_queue.put_nowait(normalized)
            return
        self.pending_log_buffer.append(normalized)

    def flush_pending_logs(self) -> None:
        while self.pending_log_buffer:
            self.log_forward_queue.put_nowait(self.pending_log_buffer.pop(0))

    async def close(self) -> None:
        await self.task_registry.cancel_all()

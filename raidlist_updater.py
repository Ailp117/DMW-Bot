# raidlist_updater.py
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Awaitable, Callable

UpdateFn = Callable[[int], Awaitable[None]]


class RaidlistUpdater:
    """
    Debounced, coalesced raidlist updater per guild.

    - mark_dirty(guild_id) schedules an update after debounce window.
    - Many changes coalesce into one Discord edit.
    - Lock prevents concurrent edits per guild.
    - If changes happen during an update, one follow-up update is scheduled.
    """

    def __init__(
        self,
        update_fn: UpdateFn,
        *,
        debounce_seconds: float = 1.5,
        cooldown_seconds: float = 0.8,
    ):
        self.update_fn = update_fn
        self.debounce = float(debounce_seconds)
        self.cooldown = float(cooldown_seconds)

        self._dirty = defaultdict(lambda: False)  # guild_id -> bool
        self._task: dict[int, asyncio.Task] = {}
        self._lock = defaultdict(asyncio.Lock)

        self._last_edit_ts = defaultdict(lambda: 0.0)  # guild_id -> monotonic timestamp
        self._generation = defaultdict(lambda: 0)      # guild_id -> int

    async def mark_dirty(self, guild_id: int) -> None:
        """Call this whenever raidlist-relevant data changed."""
        self._dirty[guild_id] = True
        self._generation[guild_id] += 1
        gen = self._generation[guild_id]

        t = self._task.get(guild_id)
        if t is None or t.done():
            self._task[guild_id] = asyncio.create_task(self._debounced_run(guild_id, gen))

    async def force_update(self, guild_id: int) -> None:
        """Run immediately (still locked + cooldown). Useful on startup or /raidlist."""
        self._dirty[guild_id] = True
        await self._run_locked(guild_id)

    async def _debounced_run(self, guild_id: int, start_gen: int) -> None:
        await asyncio.sleep(self.debounce)

        if self._generation[guild_id] != start_gen:
            newest = self._generation[guild_id]
            self._task[guild_id] = asyncio.create_task(self._debounced_run(guild_id, newest))
            return

        await self._run_locked(guild_id)

    async def _run_locked(self, guild_id: int) -> None:
        async with self._lock[guild_id]:
            now = time.monotonic()
            since = now - self._last_edit_ts[guild_id]
            if since < self.cooldown:
                await asyncio.sleep(self.cooldown - since)

            if not self._dirty[guild_id]:
                return

            self._dirty[guild_id]_]()_

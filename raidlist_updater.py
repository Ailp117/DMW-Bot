from __future__ import annotations
import asyncio
import time
from collections import defaultdict
from typing import Awaitable, Callable

UpdateFn = Callable[[int], Awaitable[None]]

class RaidlistUpdater:
    def __init__(self, update_fn: UpdateFn, *, debounce_seconds: float = 1.5, cooldown_seconds: float = 0.8):
        self.update_fn = update_fn
        self.debounce = float(debounce_seconds)
        self.cooldown = float(cooldown_seconds)
        self._dirty = defaultdict(lambda: False)
        self._gen = defaultdict(lambda: 0)
        self._task: dict[int, asyncio.Task] = {}
        self._lock = defaultdict(asyncio.Lock)
        self._last = defaultdict(lambda: 0.0)

    async def mark_dirty(self, guild_id: int) -> None:
        self._dirty[guild_id] = True
        self._gen[guild_id] += 1
        g = self._gen[guild_id]
        t = self._task.get(guild_id)
        if t is None or t.done():
            self._task[guild_id] = asyncio.create_task(self._debounced(guild_id, g))

    async def force_update(self, guild_id: int) -> None:
        self._dirty[guild_id] = True
        await self._run(guild_id)

    async def _debounced(self, guild_id: int, gen: int) -> None:
        await asyncio.sleep(self.debounce)
        if self._gen[guild_id] != gen:
            self._task[guild_id] = asyncio.create_task(self._debounced(guild_id, self._gen[guild_id]))
            return
        await self._run(guild_id)

    async def _run(self, guild_id: int) -> None:
        async with self._lock[guild_id]:
            now = time.monotonic()
            since = now - self._last[guild_id]
            if since < self.cooldown:
                await asyncio.sleep(self.cooldown - since)

            if not self._dirty[guild_id]:
                return

            self._dirty[guild_id] = False
            before = self._gen[guild_id]
            await self.update_fn(guild_id)
            self._last[guild_id] = time.monotonic()

            if self._gen[guild_id] != before:
                self._task[guild_id] = asyncio.create_task(self._debounced(guild_id, self._gen[guild_id]))

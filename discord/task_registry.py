from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable


UpdateFn = Callable[[int], Awaitable[None]]


@dataclass(slots=True)
class TaskHandle:
    name: str
    task: asyncio.Task


class SingletonTaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def start_once(self, name: str, factory: Callable[[], Awaitable[None]]) -> asyncio.Task:
        task = self._tasks.get(name)
        if task and not task.done():
            return task
        task = asyncio.create_task(factory())
        self._tasks[name] = task
        return task

    def get(self, name: str) -> asyncio.Task | None:
        return self._tasks.get(name)

    async def cancel_all(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class DebouncedGuildUpdater:
    def __init__(self, update_fn: UpdateFn, *, debounce_seconds: float = 1.5, cooldown_seconds: float = 0.8):
        self.update_fn = update_fn
        self.debounce = float(debounce_seconds)
        self.cooldown = float(cooldown_seconds)
        self._dirty = defaultdict(lambda: False)
        self._generation = defaultdict(lambda: 0)
        self._tasks: dict[int, asyncio.Task] = {}
        self._locks = defaultdict(asyncio.Lock)
        self._last_run = defaultdict(lambda: 0.0)

    async def mark_dirty(self, guild_id: int) -> None:
        self._dirty[guild_id] = True
        self._generation[guild_id] += 1
        generation = self._generation[guild_id]
        running = self._tasks.get(guild_id)
        if running is None or running.done():
            self._tasks[guild_id] = asyncio.create_task(self._debounced(guild_id, generation))

    async def force_update(self, guild_id: int) -> None:
        self._dirty[guild_id] = True
        await self._run(guild_id)

    async def _debounced(self, guild_id: int, generation: int) -> None:
        await asyncio.sleep(self.debounce)
        if self._generation[guild_id] != generation:
            self._tasks[guild_id] = asyncio.create_task(self._debounced(guild_id, self._generation[guild_id]))
            return
        await self._run(guild_id)

    async def _run(self, guild_id: int) -> None:
        async with self._locks[guild_id]:
            elapsed = time.monotonic() - self._last_run[guild_id]
            if elapsed < self.cooldown:
                await asyncio.sleep(self.cooldown - elapsed)

            if not self._dirty[guild_id]:
                return

            self._dirty[guild_id] = False
            before = self._generation[guild_id]
            await self.update_fn(guild_id)
            self._last_run[guild_id] = time.monotonic()

            if self._generation[guild_id] != before:
                self._tasks[guild_id] = asyncio.create_task(self._debounced(guild_id, self._generation[guild_id]))

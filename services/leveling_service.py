from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from db.repository import InMemoryRepository
from utils.leveling import calculate_level_from_xp


VOICE_XP_AWARD_INTERVAL = timedelta(hours=1)


@dataclass(slots=True)
class LevelUpdateResult:
    previous_level: int
    current_level: int
    xp: int


class LevelingService:
    def __init__(self) -> None:
        self._last_voice_award: dict[tuple[int, int], datetime] = {}

    def update_message_xp(
        self,
        repo: InMemoryRepository,
        *,
        guild_id: int,
        user_id: int,
        username: str | None,
        gained_xp: int = 10,
    ) -> LevelUpdateResult:
        row = repo.get_or_create_user_level(guild_id, user_id, username)
        row.username = username
        previous_level = row.level
        row.xp += gained_xp
        row.level = calculate_level_from_xp(row.xp)
        return LevelUpdateResult(previous_level=previous_level, current_level=row.level, xp=row.xp)

    def award_voice_xp_once(
        self,
        repo: InMemoryRepository,
        *,
        now: datetime,
        guild_id: int,
        user_id: int,
        username: str | None,
    ) -> bool:
        key = (guild_id, user_id)
        last_award = self._last_voice_award.get(key)
        if last_award is None:
            self._last_voice_award[key] = now
            return False
        if now - last_award < VOICE_XP_AWARD_INTERVAL:
            return False

        row = repo.get_or_create_user_level(guild_id, user_id, username)
        row.username = username
        row.xp += 1
        row.level = calculate_level_from_xp(row.xp)
        self._last_voice_award[key] = now
        return True

    def on_voice_disconnect(self, guild_id: int, user_id: int) -> None:
        self._last_voice_award.pop((guild_id, user_id), None)

    def on_voice_connect(self, guild_id: int, user_id: int, now: datetime) -> None:
        self._last_voice_award[(guild_id, user_id)] = now

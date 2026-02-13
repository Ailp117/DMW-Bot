from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from db.repository import InMemoryRepository
from utils.leveling import calculate_level_from_xp


VOICE_XP_AWARD_INTERVAL = timedelta(hours=1)
MESSAGE_XP_AWARD_INTERVAL = timedelta(seconds=30)
LEVELUP_MESSAGE_COOLDOWN = timedelta(seconds=30)


@dataclass(slots=True)
class LevelUpdateResult:
    previous_level: int
    current_level: int
    xp: int
    xp_awarded: bool


class LevelingService:
    def __init__(self) -> None:
        self._last_voice_award: dict[tuple[int, int], datetime] = {}
        self._last_message_award: dict[tuple[int, int], datetime] = {}
        self._last_levelup_announcement: dict[tuple[int, int], tuple[int, datetime]] = {}

    @staticmethod
    def _normalize_xp_gain(value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
        return max(0, parsed)

    @staticmethod
    def _normalize_ts(ts: datetime | None) -> datetime:
        if ts is None:
            return datetime.now(UTC)
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    def update_message_xp(
        self,
        repo: InMemoryRepository,
        *,
        guild_id: int,
        user_id: int,
        username: str | None,
        gained_xp: int = 10,
        now: datetime | None = None,
        min_award_interval: timedelta = MESSAGE_XP_AWARD_INTERVAL,
    ) -> LevelUpdateResult:
        timestamp = self._normalize_ts(now)
        row = repo.get_or_create_user_level(guild_id, user_id, username)
        row.username = username

        key = (guild_id, user_id)
        last_award = self._last_message_award.get(key)
        if last_award is not None and (timestamp - last_award) < min_award_interval:
            return LevelUpdateResult(
                previous_level=row.level,
                current_level=row.level,
                xp=row.xp,
                xp_awarded=False,
            )

        gained_xp_int = self._normalize_xp_gain(gained_xp)
        previous_level = int(row.level)
        row.xp = int(row.xp) + gained_xp_int
        row.level = calculate_level_from_xp(row.xp)
        self._last_message_award[key] = timestamp
        return LevelUpdateResult(previous_level=previous_level, current_level=row.level, xp=row.xp, xp_awarded=True)

    def should_announce_levelup(
        self,
        *,
        guild_id: int,
        user_id: int,
        level: int,
        now: datetime | None = None,
        min_announce_interval: timedelta = LEVELUP_MESSAGE_COOLDOWN,
    ) -> bool:
        timestamp = self._normalize_ts(now)
        key = (guild_id, user_id)
        previous = self._last_levelup_announcement.get(key)
        if previous is not None:
            previous_level, previous_at = previous
            if level <= previous_level:
                return False
            if (timestamp - previous_at) < min_announce_interval:
                return False

        self._last_levelup_announcement[key] = (level, timestamp)
        return True

    def award_voice_xp_once(
        self,
        repo: InMemoryRepository,
        *,
        now: datetime,
        guild_id: int,
        user_id: int,
        username: str | None,
    ) -> bool:
        timestamp = self._normalize_ts(now)
        key = (guild_id, user_id)
        last_award = self._last_voice_award.get(key)
        if last_award is None:
            self._last_voice_award[key] = timestamp
            return False
        if timestamp - last_award < VOICE_XP_AWARD_INTERVAL:
            return False

        row = repo.get_or_create_user_level(guild_id, user_id, username)
        row.username = username
        row.xp = int(row.xp) + 1
        row.level = calculate_level_from_xp(row.xp)
        self._last_voice_award[key] = timestamp
        return True

    def on_voice_disconnect(self, guild_id: int, user_id: int) -> None:
        key = (guild_id, user_id)
        self._last_voice_award.pop(key, None)
        self._last_message_award.pop(key, None)

    def on_voice_connect(self, guild_id: int, user_id: int, now: datetime) -> None:
        self._last_voice_award[(guild_id, user_id)] = self._normalize_ts(now)

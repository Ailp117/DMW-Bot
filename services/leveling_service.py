from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math

from db.repository import InMemoryRepository
from utils.leveling import calculate_level_from_xp


VOICE_XP_AWARD_INTERVAL = timedelta(hours=1)
MESSAGE_XP_AWARD_INTERVAL = timedelta(seconds=30)
LEVELUP_MESSAGE_COOLDOWN = timedelta(seconds=30)
DEFAULT_MESSAGE_XP_GAIN = 5


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
        except (TypeError, ValueError, OverflowError):
            parsed = 0
        return max(0, parsed)

    @staticmethod
    def _normalize_ts(ts: datetime | None) -> datetime:
        if ts is None:
            return datetime.now(UTC)
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    @staticmethod
    def _normalize_interval(raw: timedelta, fallback: timedelta) -> timedelta:
        try:
            seconds = float(raw.total_seconds())
        except Exception:
            return fallback
        if not math.isfinite(seconds) or seconds <= 0:
            return fallback
        return timedelta(seconds=seconds)

    @staticmethod
    def _normalize_total_xp(value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return max(0, parsed)

    @staticmethod
    def _normalize_positive_id(value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return parsed if parsed > 0 else 0

    def update_message_xp(
        self,
        repo: InMemoryRepository,
        *,
        guild_id: int,
        user_id: int,
        username: str | None,
        gained_xp: int = DEFAULT_MESSAGE_XP_GAIN,
        now: datetime | None = None,
        min_award_interval: timedelta = MESSAGE_XP_AWARD_INTERVAL,
    ) -> LevelUpdateResult:
        if self._normalize_positive_id(guild_id) == 0 or self._normalize_positive_id(user_id) == 0:
            return LevelUpdateResult(previous_level=0, current_level=0, xp=0, xp_awarded=False)

        timestamp = self._normalize_ts(now)
        safe_interval = self._normalize_interval(min_award_interval, MESSAGE_XP_AWARD_INTERVAL)
        row = repo.get_or_create_user_level(guild_id, user_id, username)
        row.username = username

        key = (guild_id, user_id)
        last_award = self._last_message_award.get(key)
        if last_award is not None and (timestamp - last_award) < safe_interval:
            return LevelUpdateResult(
                previous_level=max(0, int(row.level)),
                current_level=max(0, int(row.level)),
                xp=self._normalize_total_xp(row.xp),
                xp_awarded=False,
            )

        gained_xp_int = self._normalize_xp_gain(gained_xp)
        current_xp = self._normalize_total_xp(row.xp)
        row.xp = current_xp
        row.level = calculate_level_from_xp(current_xp)
        if gained_xp_int <= 0:
            return LevelUpdateResult(
                previous_level=max(0, int(row.level)),
                current_level=max(0, int(row.level)),
                xp=current_xp,
                xp_awarded=False,
            )

        previous_level = max(0, int(row.level))
        next_xp = self._normalize_total_xp(current_xp + gained_xp_int)
        row.xp = next_xp
        row.level = calculate_level_from_xp(next_xp)
        self._last_message_award[key] = timestamp
        return LevelUpdateResult(
            previous_level=previous_level,
            current_level=max(0, int(row.level)),
            xp=next_xp,
            xp_awarded=True,
        )

    def should_announce_levelup(
        self,
        *,
        guild_id: int,
        user_id: int,
        level: int,
        now: datetime | None = None,
        min_announce_interval: timedelta = LEVELUP_MESSAGE_COOLDOWN,
    ) -> bool:
        if self._normalize_positive_id(guild_id) == 0 or self._normalize_positive_id(user_id) == 0:
            return False

        try:
            normalized_level = int(level)
        except (TypeError, ValueError, OverflowError):
            return False
        if normalized_level <= 0:
            return False

        timestamp = self._normalize_ts(now)
        safe_interval = self._normalize_interval(min_announce_interval, LEVELUP_MESSAGE_COOLDOWN)
        key = (guild_id, user_id)
        previous = self._last_levelup_announcement.get(key)
        if previous is not None:
            previous_level, previous_at = previous
            if normalized_level <= previous_level:
                return False
            if (timestamp - previous_at) < safe_interval:
                return False

        self._last_levelup_announcement[key] = (normalized_level, timestamp)
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
        if self._normalize_positive_id(guild_id) == 0 or self._normalize_positive_id(user_id) == 0:
            return False

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
        current_xp = self._normalize_total_xp(row.xp)
        next_xp = self._normalize_total_xp(current_xp + 1)
        row.xp = next_xp
        row.level = calculate_level_from_xp(next_xp)
        self._last_voice_award[key] = timestamp
        return True

    def on_voice_disconnect(self, guild_id: int, user_id: int) -> None:
        key = (guild_id, user_id)
        self._last_voice_award.pop(key, None)
        self._last_message_award.pop(key, None)

    def on_voice_connect(self, guild_id: int, user_id: int, now: datetime) -> None:
        self._last_voice_award[(guild_id, user_id)] = self._normalize_ts(now)

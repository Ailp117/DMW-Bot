from __future__ import annotations

from dataclasses import dataclass
import os


TRUTHY_VALUES = {"1", "true", "yes", "on"}
VALID_DISCORD_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY_VALUES


def env_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"Invalid integer env {name}={raw!r}") from exc


@dataclass(frozen=True)
class BotConfig:
    discord_token: str
    database_url: str
    privileged_user_id: int
    db_echo: bool
    enable_message_content_intent: bool
    level_persist_interval_seconds: int
    message_xp_interval_seconds: int
    levelup_message_cooldown_seconds: int
    log_guild_id: int
    log_channel_id: int
    self_test_interval_seconds: int
    backup_interval_seconds: int
    raidlist_debug_channel_id: int
    memberlist_debug_channel_id: int
    discord_log_level: str


    def validate(self) -> None:
        if not self.database_url:
            raise ValueError("DATABASE_URL must be set")
        if self.privileged_user_id <= 0:
            raise ValueError("PRIVILEGED_USER_ID must be > 0")
        if self.level_persist_interval_seconds < 5:
            raise ValueError("LEVEL_PERSIST_INTERVAL_SECONDS must be >= 5")
        if self.message_xp_interval_seconds < 1:
            raise ValueError("MESSAGE_XP_INTERVAL_SECONDS must be >= 1")
        if self.levelup_message_cooldown_seconds < 1:
            raise ValueError("LEVELUP_MESSAGE_COOLDOWN_SECONDS must be >= 1")
        if self.self_test_interval_seconds < 30:
            raise ValueError("SELF_TEST_INTERVAL_SECONDS must be >= 30")
        if self.backup_interval_seconds < 300:
            raise ValueError("BACKUP_INTERVAL_SECONDS must be >= 300")
        if self.log_guild_id < 0 or self.log_channel_id < 0:
            raise ValueError("LOG_GUILD_ID/LOG_CHANNEL_ID must be >= 0")
        if self.raidlist_debug_channel_id < 0 or self.memberlist_debug_channel_id < 0:
            raise ValueError("Debug channel IDs must be >= 0")
        if self.discord_log_level not in VALID_DISCORD_LOG_LEVELS:
            valid = ", ".join(sorted(VALID_DISCORD_LOG_LEVELS))
            raise ValueError(f"DISCORD_LOG_LEVEL must be one of: {valid}")


def load_config() -> BotConfig:
    cfg = BotConfig(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        database_url=os.getenv("DATABASE_URL", ""),
        privileged_user_id=env_int("PRIVILEGED_USER_ID", default=403988960638009347),
        db_echo=env_bool("DB_ECHO", default=False),
        enable_message_content_intent=env_bool("ENABLE_MESSAGE_CONTENT_INTENT", default=True),
        level_persist_interval_seconds=env_int("LEVEL_PERSIST_INTERVAL_SECONDS", default=120),
        message_xp_interval_seconds=env_int("MESSAGE_XP_INTERVAL_SECONDS", default=15),
        levelup_message_cooldown_seconds=env_int("LEVELUP_MESSAGE_COOLDOWN_SECONDS", default=20),
        log_guild_id=env_int("LOG_GUILD_ID", default=0),
        log_channel_id=env_int("LOG_CHANNEL_ID", default=0),
        self_test_interval_seconds=env_int("SELF_TEST_INTERVAL_SECONDS", default=900),
        backup_interval_seconds=env_int("BACKUP_INTERVAL_SECONDS", default=21600),
        raidlist_debug_channel_id=env_int("RAIDLIST_DEBUG_CHANNEL_ID", default=0),
        memberlist_debug_channel_id=env_int("MEMBERLIST_DEBUG_CHANNEL_ID", default=0),
        discord_log_level=os.getenv("DISCORD_LOG_LEVEL", "INFO").strip().upper(),
    )
    cfg.validate()
    return cfg

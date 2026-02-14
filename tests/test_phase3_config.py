from __future__ import annotations

import pytest

from bot.config import env_bool, load_config


def test_env_bool_parser_truthy_falsy_defaults(monkeypatch):
    monkeypatch.setenv("FLAG", "true")
    assert env_bool("FLAG") is True

    monkeypatch.setenv("FLAG", "off")
    assert env_bool("FLAG") is False

    monkeypatch.delenv("FLAG", raising=False)
    assert env_bool("FLAG", default=True) is True


def test_intent_toggle_reaches_config(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("ENABLE_MESSAGE_CONTENT_INTENT", "false")
    cfg = load_config()
    assert cfg.enable_message_content_intent is False


def test_discord_log_level_defaults_to_info(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.delenv("DISCORD_LOG_LEVEL", raising=False)
    cfg = load_config()
    assert cfg.discord_log_level == "INFO"


def test_discord_log_level_validation_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DISCORD_LOG_LEVEL", "trace")
    with pytest.raises(ValueError, match="DISCORD_LOG_LEVEL must be one of"):
        load_config()


def test_log_forward_queue_size_validation_rejects_negative(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("LOG_FORWARD_QUEUE_MAX_SIZE", "-1")
    with pytest.raises(ValueError, match="LOG_FORWARD_QUEUE_MAX_SIZE must be >= 0"):
        load_config()

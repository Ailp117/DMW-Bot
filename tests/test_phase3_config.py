from __future__ import annotations

import os

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

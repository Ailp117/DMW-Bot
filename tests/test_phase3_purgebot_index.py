from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.runtime as runtime_mod
from bot.runtime import BOT_MESSAGE_KIND, BOT_MESSAGE_CACHE_PREFIX, RewriteDiscordBot
from utils.hashing import sha256_text


def _make_bot(repo, *, bot_user_id: int = 99) -> RewriteDiscordBot:
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    return bot


def test_track_bot_message_stores_message_with_bot_user_id(repo):
    bot = _make_bot(repo, bot_user_id=403)
    guild = SimpleNamespace(id=1)
    channel = SimpleNamespace(id=77, guild=guild)
    author = SimpleNamespace(id=403)
    message = SimpleNamespace(id=555, guild=guild, channel=channel, author=author)

    RewriteDiscordBot._track_bot_message(bot, message)

    key = f"{BOT_MESSAGE_CACHE_PREFIX}:1:77:403:555"
    row = repo.get_debug_cache(key)
    assert row is not None
    assert row.kind == BOT_MESSAGE_KIND
    assert row.guild_id == 1
    assert row.raid_id == 77
    assert row.message_id == 555
    assert row.payload_hash == sha256_text("403:555")


@pytest.mark.asyncio
async def test_delete_bot_messages_uses_index_and_clears_refs(repo, monkeypatch):
    bot = _make_bot(repo, bot_user_id=99)
    settings = repo.ensure_settings(1, "Guild")
    settings.raidlist_channel_id = 77
    settings.raidlist_message_id = 555

    repo.upsert_debug_cache(
        cache_key=f"{BOT_MESSAGE_CACHE_PREFIX}:1:77:99:555",
        kind=BOT_MESSAGE_KIND,
        guild_id=1,
        raid_id=77,
        message_id=555,
        payload_hash=sha256_text("99:555"),
    )

    fake_message = SimpleNamespace(id=555, author=SimpleNamespace(id=99))
    channel = SimpleNamespace(id=77, guild=SimpleNamespace(id=1))

    async def _fake_fetch_message(_channel, message_id):
        if int(message_id) == 555:
            return fake_message
        return None

    async def _fake_delete_message(_message):
        return True

    monkeypatch.setattr(runtime_mod, "_safe_fetch_message", _fake_fetch_message)
    monkeypatch.setattr(runtime_mod, "_safe_delete_message", _fake_delete_message)

    deleted = await RewriteDiscordBot._delete_bot_messages_in_channel(
        bot,
        channel,
        history_limit=50,
        scan_history=False,
    )

    assert deleted == 1
    assert settings.raidlist_message_id is None
    assert repo.get_debug_cache(f"{BOT_MESSAGE_CACHE_PREFIX}:1:77:99:555") is None


@pytest.mark.asyncio
async def test_delete_bot_messages_handles_history_failures(repo, monkeypatch):
    bot = _make_bot(repo, bot_user_id=99)

    repo.upsert_debug_cache(
        cache_key=f"{BOT_MESSAGE_CACHE_PREFIX}:1:77:99:555",
        kind=BOT_MESSAGE_KIND,
        guild_id=1,
        raid_id=77,
        message_id=555,
        payload_hash=sha256_text("99:555"),
    )

    fake_message = SimpleNamespace(id=555, author=SimpleNamespace(id=99))

    async def _fake_fetch_message(_channel, message_id):
        if int(message_id) == 555:
            return fake_message
        return None

    async def _fake_delete_message(_message):
        return True

    class _Channel:
        id = 77
        guild = SimpleNamespace(id=1)

        def history(self, *, limit: int = 0):
            raise RuntimeError("history unavailable")

    monkeypatch.setattr(runtime_mod, "_safe_fetch_message", _fake_fetch_message)
    monkeypatch.setattr(runtime_mod, "_safe_delete_message", _fake_delete_message)

    deleted = await RewriteDiscordBot._delete_bot_messages_in_channel(
        bot,
        _Channel(),
        history_limit=50,
        scan_history=True,
    )

    assert deleted == 1

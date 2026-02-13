import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main


class _FakePerms:
    def __init__(self, send_messages: bool):
        self.send_messages = send_messages


class _FakeTextChannel:
    def __init__(self, channel_id: int, can_send: bool = True):
        self.id = channel_id
        self._can_send = can_send

    def permissions_for(self, _member):
        return _FakePerms(self._can_send)


class _FakeGuild:
    def __init__(self, guild_id: int, channel):
        self.id = guild_id
        self.me = object()
        self._channel = channel

    def get_channel(self, channel_id: int):
        if self._channel and self._channel.id == channel_id:
            return self._channel
        return None


class LiveLogChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_log_channel_uses_configured_debug_server_channel(self):
        channel = _FakeTextChannel(main.LOG_CHANNEL_ID)
        guild = _FakeGuild(main.LOG_GUILD_ID, channel)
        bot_like = SimpleNamespace(get_guild=lambda gid: guild if gid == main.LOG_GUILD_ID else None)

        with patch.object(main.discord, "TextChannel", _FakeTextChannel):
            resolved = await main.RaidBot._resolve_log_channel(bot_like)

        self.assertIs(resolved, channel)


if __name__ == "__main__":
    unittest.main()

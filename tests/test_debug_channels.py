import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import raidlist
import views_raid


class _FakeMessage:
    def __init__(self, mid=1):
        self.id = mid
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _FakeChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}
        self._next_id = 10

    async def send(self, content=None, embed=None):
        msg = _FakeMessage(self._next_id)
        self._next_id += 1
        self.messages[msg.id] = msg
        self.sent.append({"content": content, "embed": embed, "id": msg.id})
        return msg

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise Exception("not found")
        return self.messages[message_id]


class _FakeClient:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, _channel_id):
        return self.channel

    async def fetch_channel(self, _channel_id):
        return self.channel


class _FakeSession:
    def __init__(self, store):
        self.store = store

    async def get(self, _model, key):
        return self.store.get(key)

    def add(self, row):
        self.store[row.cache_key] = row


class DebugChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_raidlist_debug_skips_debug_server(self):
        channel = _FakeChannel()
        client = _FakeClient(channel)
        guild = SimpleNamespace(id=raidlist.LOG_GUILD_ID, name="Debug")
        embed = SimpleNamespace(fields=[])

        await raidlist._mirror_raidlist_debug_embed(client, guild, embed)
        self.assertEqual(channel.sent, [])

    async def test_memberlist_debug_skips_debug_server(self):
        channel = _FakeChannel()
        client = _FakeClient(channel)
        guild = SimpleNamespace(id=views_raid.LOG_GUILD_ID, name="Debug")
        interaction = SimpleNamespace(guild=guild, client=client)
        raid = SimpleNamespace(id=1, dungeon="Test")

        await views_raid._mirror_memberlist_debug(interaction, raid, ["line"])
        self.assertEqual(channel.sent, [])

    async def test_raidlist_debug_avoids_reposting_when_payload_unchanged(self):
        channel = _FakeChannel()
        client = _FakeClient(channel)
        guild = SimpleNamespace(id=999999, name="Guild")
        cache_store = {}

        @asynccontextmanager
        async def _fake_session_scope():
            yield _FakeSession(cache_store)

        class _Field:
            def __init__(self):
                self.name = "n"
                self.value = "v"
                self.inline = False

        embed = SimpleNamespace(fields=[_Field()])

        with patch.object(raidlist, "session_scope", _fake_session_scope):
            await raidlist._mirror_raidlist_debug_embed(client, guild, embed)
            await raidlist._mirror_raidlist_debug_embed(client, guild, embed)

        self.assertEqual(len(channel.sent), 1)

    async def test_memberlist_debug_avoids_reposting_when_payload_unchanged(self):
        channel = _FakeChannel()
        client = _FakeClient(channel)
        guild = SimpleNamespace(id=888888, name="Guild")
        interaction = SimpleNamespace(guild=guild, client=client)
        raid = SimpleNamespace(id=1, dungeon="Test")
        cache_store = {}

        @asynccontextmanager
        async def _fake_session_scope():
            yield _FakeSession(cache_store)

        with patch.object(views_raid, "session_scope", _fake_session_scope):
            await views_raid._mirror_memberlist_debug(interaction, raid, ["line"])
            await views_raid._mirror_memberlist_debug(interaction, raid, ["line"])

        self.assertEqual(len(channel.sent), 1)


if __name__ == "__main__":
    unittest.main()

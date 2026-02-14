from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot
from services.raid_service import create_raid_from_modal


class _DummyMessage:
    def __init__(self, author_id: int) -> None:
        self.author = SimpleNamespace(id=author_id)
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class _DummyChannel:
    def __init__(self, messages: list[_DummyMessage]) -> None:
        self.id = 222
        self._messages = messages

    def history(self, *, limit: int = 100):
        async def _iterate():
            for message in self._messages[:limit]:
                yield message

        return _iterate()


@pytest.mark.asyncio
async def test_delete_bot_messages_in_channel_filters_by_author():
    bot = object.__new__(RewriteDiscordBot)
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=99))
    messages = [_DummyMessage(author_id=99), _DummyMessage(author_id=42), _DummyMessage(author_id=99)]
    channel = _DummyChannel(messages)

    deleted = await RewriteDiscordBot._delete_bot_messages_in_channel(bot, channel, history_limit=10)

    assert deleted == 2
    assert messages[0].deleted is True
    assert messages[1].deleted is False
    assert messages[2].deleted is True


@pytest.mark.asyncio
async def test_rebuild_memberlists_clears_slots_then_recreates(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    created = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=9900,
    ).raid
    repo.upsert_posted_slot(raid_id=created.id, day_label="14.02.2026", time_label="20:00", channel_id=22, message_id=501)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=55))
    channel = _DummyChannel(messages=[_DummyMessage(author_id=55)])

    async def _fake_delete_slot_message(_row):
        return True

    async def _fake_delete_bot_messages_in_channel(_channel, *, history_limit: int = 5000):
        return 3

    async def _fake_sync_memberlists(raid_id: int):
        assert repo.list_posted_slots(raid_id) == {}
        repo.upsert_posted_slot(raid_id=raid_id, day_label="14.02.2026", time_label="20:00", channel_id=22, message_id=777)
        return (1, 0, 0)

    bot._delete_slot_message = _fake_delete_slot_message
    bot._delete_bot_messages_in_channel = _fake_delete_bot_messages_in_channel
    bot._sync_memberlist_messages_for_raid = _fake_sync_memberlists

    stats = await RewriteDiscordBot._rebuild_memberlists_for_guild(bot, 1, participants_channel=channel)

    assert stats.raids == 1
    assert stats.cleared_slot_rows == 1
    assert stats.deleted_slot_messages == 1
    assert stats.deleted_legacy_messages == 3
    assert stats.created == 1
    assert stats.updated == 0
    assert stats.deleted == 0
    assert len(repo.list_posted_slots(created.id)) == 1

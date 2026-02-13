from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot


async def _empty_fetch_members(*, limit=None):
    if False:
        yield None


async def _raising_fetch_members(*, limit=None):
    raise AssertionError("fetch_members should not be called when members intent is disabled")
    if False:
        yield None


async def _single_fetch_member(*, limit=None):
    yield SimpleNamespace(id=3002, bot=False, display_name="Echo", global_name=None, name="echo")


@pytest.mark.asyncio
async def test_sync_guild_usernames_inserts_member_names(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._state_lock = asyncio.Lock()
    bot._username_sync_next_run_by_guild = {}
    bot._level_state_dirty = False

    guild = SimpleNamespace(
        id=1,
        members=[
            SimpleNamespace(id=1001, bot=False, display_name="Alpha", global_name=None, name="alpha"),
            SimpleNamespace(id=1002, bot=False, display_name="Bravo", global_name=None, name="bravo"),
            SimpleNamespace(id=9999, bot=True, display_name="Bot", global_name=None, name="bot"),
        ],
        member_count=2,
        fetch_members=_empty_fetch_members,
    )

    scanned, changed = await RewriteDiscordBot._sync_guild_usernames(bot, guild, force=True)

    assert scanned == 2
    assert changed == 2
    assert bot.repo.user_levels[(1, 1001)].username == "Alpha"
    assert bot.repo.user_levels[(1, 1002)].username == "Bravo"


@pytest.mark.asyncio
async def test_sync_guild_usernames_updates_changed_name(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._state_lock = asyncio.Lock()
    bot._username_sync_next_run_by_guild = {}
    bot._level_state_dirty = False

    row = repo.get_or_create_user_level(1, 1001, "OldName")
    row.username = "OldName"

    guild = SimpleNamespace(
        id=1,
        members=[SimpleNamespace(id=1001, bot=False, display_name="NewName", global_name=None, name="new")],
        member_count=1,
        fetch_members=_empty_fetch_members,
    )

    scanned, changed = await RewriteDiscordBot._sync_guild_usernames(bot, guild, force=True)

    assert scanned == 1
    assert changed == 1
    assert bot.repo.user_levels[(1, 1001)].username == "NewName"


@pytest.mark.asyncio
async def test_collect_guild_usernames_skips_fetch_without_members_intent():
    bot = object.__new__(RewriteDiscordBot)
    bot._connection = SimpleNamespace(intents=SimpleNamespace(members=False))

    guild = SimpleNamespace(
        id=9,
        members=[SimpleNamespace(id=3001, bot=False, display_name="Delta", global_name=None, name="delta")],
        member_count=2,
        fetch_members=_raising_fetch_members,
    )

    usernames = await RewriteDiscordBot._collect_guild_member_usernames(bot, guild)

    assert usernames == {3001: "Delta"}


@pytest.mark.asyncio
async def test_collect_guild_usernames_fetches_missing_members_when_intent_enabled():
    bot = object.__new__(RewriteDiscordBot)
    bot._connection = SimpleNamespace(intents=SimpleNamespace(members=True))

    guild = SimpleNamespace(
        id=9,
        members=[SimpleNamespace(id=3001, bot=False, display_name="Delta", global_name=None, name="delta")],
        member_count=2,
        fetch_members=_single_fetch_member,
    )

    usernames = await RewriteDiscordBot._collect_guild_member_usernames(bot, guild)

    assert usernames == {3001: "Delta", 3002: "Echo"}


def test_plain_user_list_uses_db_username_fallback(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot.get_guild = lambda _guild_id: None

    row = repo.get_or_create_user_level(1, 2001, "PersistedName")
    row.username = "PersistedName"

    rendered = RewriteDiscordBot._plain_user_list_for_embed(bot, 1, {2001})

    assert "PersistedName" in rendered
    assert "User 2001" not in rendered

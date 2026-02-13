from __future__ import annotations

from utils.hashing import sha256_text


def test_payload_hash_skips_duplicate_updates(repo):
    payload = "same payload"
    payload_hash = sha256_text(payload)

    first = repo.upsert_debug_cache(
        cache_key="raidlist:1:0",
        kind="raidlist",
        guild_id=1,
        raid_id=None,
        message_id=10,
        payload_hash=payload_hash,
    )

    second = repo.get_debug_cache("raidlist:1:0")
    assert second is not None
    assert second.payload_hash == first.payload_hash

    repo.upsert_debug_cache(
        cache_key="raidlist:1:0",
        kind="raidlist",
        guild_id=1,
        raid_id=None,
        message_id=10,
        payload_hash=payload_hash,
    )

    third = repo.get_debug_cache("raidlist:1:0")
    assert third is not None
    assert third.message_id == 10
    assert third.payload_hash == payload_hash


def test_list_debug_cache_uses_kind_guild_raid_filters(repo):
    repo.upsert_debug_cache(
        cache_key="botmsg:1:10:99:1001",
        kind="bot_message",
        guild_id=1,
        raid_id=10,
        message_id=1001,
        payload_hash=sha256_text("a"),
    )
    repo.upsert_debug_cache(
        cache_key="botmsg:1:11:99:1002",
        kind="bot_message",
        guild_id=1,
        raid_id=11,
        message_id=1002,
        payload_hash=sha256_text("b"),
    )
    repo.upsert_debug_cache(
        cache_key="raidlist:2:0",
        kind="raidlist",
        guild_id=2,
        raid_id=None,
        message_id=2000,
        payload_hash=sha256_text("c"),
    )

    rows_exact = repo.list_debug_cache(kind="bot_message", guild_id=1, raid_id=10)
    assert sorted(int(row.message_id) for row in rows_exact) == [1001]

    rows_kind_guild = repo.list_debug_cache(kind="bot_message", guild_id=1)
    assert sorted(int(row.message_id) for row in rows_kind_guild) == [1001, 1002]

    rows_kind = repo.list_debug_cache(kind="bot_message")
    assert sorted(int(row.message_id) for row in rows_kind) == [1001, 1002]


def test_upsert_debug_cache_reindexes_when_scope_changes(repo):
    repo.upsert_debug_cache(
        cache_key="botmsg:1:10:99:1001",
        kind="bot_message",
        guild_id=1,
        raid_id=10,
        message_id=1001,
        payload_hash=sha256_text("a"),
    )
    repo.upsert_debug_cache(
        cache_key="botmsg:1:10:99:1001",
        kind="bot_message",
        guild_id=2,
        raid_id=22,
        message_id=1001,
        payload_hash=sha256_text("b"),
    )

    old_scope = repo.list_debug_cache(kind="bot_message", guild_id=1, raid_id=10)
    new_scope = repo.list_debug_cache(kind="bot_message", guild_id=2, raid_id=22)
    assert old_scope == []
    assert len(new_scope) == 1
    assert int(new_scope[0].guild_id) == 2
    assert int(new_scope[0].raid_id or 0) == 22

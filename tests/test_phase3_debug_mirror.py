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

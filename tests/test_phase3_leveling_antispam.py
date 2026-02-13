from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.leveling_service import LevelingService


def test_message_xp_cooldown_blocks_spam_awards(repo):
    service = LevelingService()
    t0 = datetime(2026, 2, 13, 18, 0, 0, tzinfo=UTC)

    first = service.update_message_xp(
        repo,
        guild_id=1,
        user_id=500,
        username="User500",
        now=t0,
        min_award_interval=timedelta(seconds=15),
    )
    second = service.update_message_xp(
        repo,
        guild_id=1,
        user_id=500,
        username="User500",
        now=t0 + timedelta(seconds=5),
        min_award_interval=timedelta(seconds=15),
    )
    third = service.update_message_xp(
        repo,
        guild_id=1,
        user_id=500,
        username="User500",
        now=t0 + timedelta(seconds=16),
        min_award_interval=timedelta(seconds=15),
    )

    assert first.xp_awarded is True
    assert second.xp_awarded is False
    assert third.xp_awarded is True

    row = repo.get_or_create_user_level(1, 500, "User500")
    assert row.xp == 10


def test_levelup_announcement_deduplicates_fast_repeats():
    service = LevelingService()
    t0 = datetime(2026, 2, 13, 18, 30, 0, tzinfo=UTC)

    first = service.should_announce_levelup(
        guild_id=1,
        user_id=600,
        level=3,
        now=t0,
        min_announce_interval=timedelta(seconds=20),
    )
    second = service.should_announce_levelup(
        guild_id=1,
        user_id=600,
        level=3,
        now=t0 + timedelta(seconds=1),
        min_announce_interval=timedelta(seconds=20),
    )
    third = service.should_announce_levelup(
        guild_id=1,
        user_id=600,
        level=4,
        now=t0 + timedelta(seconds=5),
        min_announce_interval=timedelta(seconds=20),
    )
    fourth = service.should_announce_levelup(
        guild_id=1,
        user_id=600,
        level=4,
        now=t0 + timedelta(seconds=30),
        min_announce_interval=timedelta(seconds=20),
    )

    assert first is True
    assert second is False
    assert third is False
    assert fourth is True

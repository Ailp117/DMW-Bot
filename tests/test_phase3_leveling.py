from __future__ import annotations

from datetime import UTC, datetime

from services.leveling_service import LevelingService
from utils.leveling import calculate_level_from_xp, xp_needed_for_level
from utils.text import contains_approved_keyword, contains_nanomon_keyword


def test_level_threshold_math():
    assert xp_needed_for_level(0) == 0
    assert xp_needed_for_level(1) == 100
    assert xp_needed_for_level(2) == 250
    assert calculate_level_from_xp(99) == 0
    assert calculate_level_from_xp(100) == 1
    assert calculate_level_from_xp(250) == 2


def test_level_thresholds_are_always_integer_and_monotonic():
    last_value = -1
    for level in range(0, 500):
        needed = xp_needed_for_level(level)
        assert isinstance(needed, int)
        assert needed >= 0
        assert needed > last_value
        last_value = needed


def test_message_xp_gain_is_normalized_to_integer(repo):
    service = LevelingService()
    result = service.update_message_xp(
        repo,
        guild_id=1,
        user_id=42,
        username="User42",
        gained_xp=7.9,  # type: ignore[arg-type]
        now=datetime(2026, 2, 13, 21, 0, 0, tzinfo=UTC),
    )

    assert result.xp_awarded is True
    assert result.xp == 7
    assert isinstance(result.xp, int)


def test_keyword_helpers_word_boundary():
    assert contains_nanomon_keyword("nanomon") is True
    assert contains_nanomon_keyword("xnanomonx") is False
    assert contains_approved_keyword("approved") is True
    assert contains_approved_keyword("preapproved") is False

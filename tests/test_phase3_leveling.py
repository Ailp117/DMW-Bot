from __future__ import annotations

from utils.leveling import calculate_level_from_xp, xp_needed_for_level
from utils.text import contains_approved_keyword, contains_nanomon_keyword


def test_level_threshold_math():
    assert xp_needed_for_level(0) == 0
    assert xp_needed_for_level(1) == 100
    assert xp_needed_for_level(2) == 250
    assert calculate_level_from_xp(99) == 0
    assert calculate_level_from_xp(100) == 1
    assert calculate_level_from_xp(250) == 2


def test_keyword_helpers_word_boundary():
    assert contains_nanomon_keyword("nanomon") is True
    assert contains_nanomon_keyword("xnanomonx") is False
    assert contains_approved_keyword("approved") is True
    assert contains_approved_keyword("preapproved") is False

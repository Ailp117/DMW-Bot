from __future__ import annotations

from math import isqrt


def xp_needed_for_level(level: int) -> int:
    safe_level = max(0, int(level))
    return (25 * safe_level * safe_level) + (75 * safe_level)


def calculate_level_from_xp(total_xp: int) -> int:
    safe_xp = max(0, int(total_xp))
    discriminant = 5625 + (100 * safe_xp)
    level = max(0, (isqrt(discriminant) - 75) // 50)

    while xp_needed_for_level(level + 1) <= safe_xp:
        level += 1
    while xp_needed_for_level(level) > safe_xp:
        level -= 1

    return level

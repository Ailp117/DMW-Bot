from __future__ import annotations

from math import isqrt


def xp_needed_for_level(level: int) -> int:
    """Total XP threshold required to be at a given level."""
    safe_level = max(0, level)
    # Sum of arithmetic progression for level-up steps: 100, 150, 200, ...
    # threshold(level) = 25*level^2 + 75*level
    return (25 * safe_level * safe_level) + (75 * safe_level)


def calculate_level_from_xp(total_xp: int) -> int:
    """Calculate level in O(1) from XP using inverse quadratic threshold."""
    safe_xp = max(0, total_xp)

    # Solve 25*l^2 + 75*l <= xp for max integer l.
    # l = floor((-75 + sqrt(75^2 + 100*xp)) / 50)
    discriminant = 5625 + (100 * safe_xp)
    level = max(0, (isqrt(discriminant) - 75) // 50)

    # Correct for integer sqrt rounding at boundaries.
    while xp_needed_for_level(level + 1) <= safe_xp:
        level += 1
    while xp_needed_for_level(level) > safe_xp:
        level -= 1

    return level

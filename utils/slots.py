from __future__ import annotations

from typing import Dict, List, Set, Tuple


def memberlist_threshold(min_players: int) -> int:
    return min_players if min_players > 0 else 1


def memberlist_target_label(min_players: int) -> str:
    return str(min_players) if min_players > 0 else "1+"


def compute_qualified_slot_users(
    *,
    days: list[str],
    times: list[str],
    day_users: Dict[str, Set[int]],
    time_users: Dict[str, Set[int]],
    threshold: int,
) -> tuple[Dict[Tuple[str, str], List[int]], Set[int]]:
    qualified: Dict[Tuple[str, str], List[int]] = {}
    all_users: Set[int] = set()

    for day in days:
        for time_label in times:
            users = sorted(day_users.get(day, set()).intersection(time_users.get(time_label, set())))
            if len(users) < threshold:
                continue
            qualified[(day, time_label)] = users
            all_users.update(users)

    return qualified, all_users

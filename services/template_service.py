from __future__ import annotations

import json

from db.repository import InMemoryRepository, RaidTemplateRecord
from utils.text import normalize_list


AUTO_DUNGEON_TEMPLATE_NAME = "_auto_dungeon_default"


def dump_template_data(days: list[str], times: list[str], min_players: int) -> str:
    payload = {
        "days": days,
        "times": times,
        "min_players": max(0, int(min_players)),
    }
    return json.dumps(payload, ensure_ascii=False)


def load_template_data(template_data: str) -> tuple[list[str], list[str], int]:
    payload = json.loads(template_data or "{}")
    days = normalize_list(",".join(payload.get("days") or []))
    times = normalize_list(",".join(payload.get("times") or []))
    try:
        min_players = max(0, int(payload.get("min_players", 0)))
    except (TypeError, ValueError):
        min_players = 0
    return days, times, min_players


def get_auto_template_defaults(
    repo: InMemoryRepository,
    *,
    guild_id: int,
    dungeon_id: int,
    templates_enabled: bool,
    default_min_players: int,
) -> tuple[list[str], list[str], int]:
    if not templates_enabled:
        return [], [], max(0, int(default_min_players))

    row = repo.get_template(
        guild_id=guild_id,
        dungeon_id=dungeon_id,
        template_name=AUTO_DUNGEON_TEMPLATE_NAME,
    )
    if row is None:
        return [], [], max(0, int(default_min_players))
    return load_template_data(row.template_data)


def upsert_auto_template(
    repo: InMemoryRepository,
    *,
    guild_id: int,
    dungeon_id: int,
    days: list[str],
    times: list[str],
    min_players: int,
) -> RaidTemplateRecord:
    payload = dump_template_data(days, times, min_players)
    return repo.upsert_template(
        guild_id=guild_id,
        dungeon_id=dungeon_id,
        template_name=AUTO_DUNGEON_TEMPLATE_NAME,
        template_data=payload,
    )

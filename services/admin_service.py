from __future__ import annotations

from db.repository import InMemoryRepository


def cancel_all_open_raids(repo: InMemoryRepository, *, guild_id: int) -> int:
    return repo.cancel_open_raids_for_guild(guild_id)


def list_active_dungeons(repo: InMemoryRepository) -> list[str]:
    return [row.name for row in repo.list_active_dungeons()]


def resolve_remote_target(repo: InMemoryRepository, raw_value: str) -> tuple[int | None, str | None]:
    guild_id, error = repo.resolve_remote_target(raw_value)
    if guild_id is not None:
        return guild_id, None

    if error == "missing":
        return None, "Please provide a guild id or name."
    if error == "ambiguous":
        return None, "Ambiguous guild name."
    return None, "Guild not found."

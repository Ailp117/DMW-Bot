from __future__ import annotations

from dataclasses import dataclass

from db.repository import RaidRecord
from utils.hashing import sha256_text


@dataclass(slots=True)
class RaidlistRender:
    guild_id: int
    title: str
    body: str
    payload_hash: str


def render_raidlist(guild_id: int, guild_name: str, raids: list[RaidRecord]) -> RaidlistRender:
    lines: list[str] = []
    for raid in raids[:25]:
        jump = "(no message)" if raid.message_id is None else f"/channels/{raid.guild_id}/{raid.channel_id}/{raid.message_id}"
        lines.append(
            f"- {raid.dungeon} | ID {raid.display_id} | Min {raid.min_players} | {jump}"
        )

    body = "No open raids." if not lines else "\n".join(lines)
    title = f"Open raids for {guild_name}"
    payload = f"{title}\n{body}"
    return RaidlistRender(guild_id=guild_id, title=title, body=body, payload_hash=sha256_text(payload))


class RaidlistHashCache:
    def __init__(self) -> None:
        self._hash_by_guild: dict[int, str] = {}

    def should_publish(self, render: RaidlistRender) -> bool:
        previous = self._hash_by_guild.get(render.guild_id)
        if previous == render.payload_hash:
            return False
        self._hash_by_guild[render.guild_id] = render.payload_hash
        return True

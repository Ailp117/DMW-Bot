from __future__ import annotations

from dataclasses import dataclass

from db.repository import RaidRecord
from utils.hashing import sha256_text
from utils.slots import memberlist_target_label


@dataclass(slots=True)
class RaidlistRender:
    guild_id: int
    title: str
    body: str
    payload_hash: str


def render_raidlist(guild_id: int, guild_name: str, raids: list[RaidRecord]) -> RaidlistRender:
    def _jump(channel_id: int, message_id: int | None) -> str:
        if message_id is None:
            return "`(noch kein Link)`"
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    lines: list[str] = []
    for raid in raids[:25]:
        jump = _jump(raid.channel_id, raid.message_id)
        target = memberlist_target_label(raid.min_players)
        lines.append(
            f"• **{raid.dungeon}** | 🆔 `{raid.display_id}` | 👥 Min `{target}`\n"
            f"  ↳ {jump}"
        )

    body = "Keine offenen Raids." if not lines else "\n".join(lines)
    title = f"📌 Open raids for {guild_name}"
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

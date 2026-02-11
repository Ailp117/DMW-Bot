from __future__ import annotations

import hashlib
import json
import discord
from sqlalchemy import select

from db import get_session
from models import GuildSettings, Raid

_LAST_HASH: dict[int, str] = {}


def _hash_embed(embed: discord.Embed) -> str:
    payload = json.dumps(embed.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def raid_jump_url(guild_id: int, channel_id: int, message_id: int | None) -> str:
    if not message_id:
        return "`(noch kein link)`"
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


async def refresh_raidlist_for_guild(client: discord.Client, guild_id: int) -> None:
    guild = client.get_guild(guild_id)
    if not guild:
        return

    async with await get_session() as session:
        s = await session.get(GuildSettings, guild_id)
        if not s or not s.raidlist_channel_id:
            return

        raids = (await session.execute(
            select(Raid).where(Raid.guild_id == guild_id, Raid.status == "open").order_by(Raid.created_at.desc())
        )).scalars().all()

    e = discord.Embed(title="📌 Offene Raids", description=f"Server: **{guild.name}**")
    if not raids:
        e.add_field(name="Status", value="Keine offenen Raids.", inline=False)
    else:
        lines = []
        for r in raids[:25]:
            url = raid_jump_url(r.guild_id, r.channel_id, r.message_id)
            lines.append(f"• **{r.dungeon}** | 🆔 `{r.id}` | Min/Slot `{r.min_players}` | {url}")
        e.add_field(name="Liste", value="\n".join(lines)[:1024], inline=False)
    e.set_footer(text="Auto-Update aktiv.")

    h = _hash_embed(e)
    if _LAST_HASH.get(guild_id) == h:
        return

    channel = client.get_channel(int(s.raidlist_channel_id)) or await client.fetch_channel(int(s.raidlist_channel_id))
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return

    # edit or create
    if s.raidlist_message_id:
        try:
            msg = await channel.fetch_message(int(s.raidlist_message_id))
            await msg.edit(embed=e, content=None)
            _LAST_HASH[guild_id] = h
            return
        except (discord.NotFound, discord.Forbidden):
            pass

    msg = await channel.send(embed=e)
    async with await get_session() as session:
        s2 = await session.get(GuildSettings, guild_id)
        if s2:
            s2.raidlist_message_id = msg.id
            await session.commit()
    _LAST_HASH[guild_id] = h


async def schedule_raidlist_refresh(client: discord.Client, guild_id: int) -> None:
    upd = getattr(client, "raidlist_updater", None)
    if upd:
        await upd.mark_dirty(guild_id)
    else:
        await refresh_raidlist_for_guild(client, guild_id)


async def force_raidlist_refresh(client: discord.Client, guild_id: int) -> None:
    upd = getattr(client, "raidlist_updater", None)
    if upd:
        await upd.force_update(guild_id)
    else:
        await refresh_raidlist_for_guild(client, guild_id)

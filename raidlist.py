# raidlist.py
from __future__ import annotations

import hashlib
import json
import discord
from sqlalchemy import select

from db import get_session
from models import GuildSettings, Raid
from helpers import raid_jump_url, get_guild_settings


# ✅ Cache: guild_id -> last embed hash
_LAST_EMBED_HASH: dict[int, str] = {}


def _hash_embed(embed: discord.Embed) -> str:
    """
    Create a stable hash for an embed, so we can skip Discord edits when nothing changed.
    """
    data = embed.to_dict()
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def get_open_raids_for_guild(session, guild_id: int):
    res = await session.execute(
        select(Raid)
        .where(Raid.guild_id == guild_id, Raid.status == "open")
        .order_by(Raid.created_at.desc())
    )
    return res.scalars().all()


async def build_raidlist_embed(guild: discord.Guild, raids: list[Raid]) -> discord.Embed:
    e = discord.Embed(title="📌 Offene Raids", description=f"Server: **{guild.name}**")
    if not raids:
        e.add_field(name="Status", value="Keine offenen Raids.", inline=False)
        e.set_footer(text="Diese Nachricht wird automatisch aktualisiert.")
        return e

    lines = []
    for r in raids[:25]:
        url = raid_jump_url(r)
        lines.append(f"• **{r.dungeon}** | 🆔 **{r.id}** | Min/Slot: **{r.min_players}** | {url}")

    e.add_field(name="Liste", value="\n".join(lines)[:1024], inline=False)
    e.set_footer(text="Diese Nachricht wird automatisch aktualisiert.")
    return e


async def refresh_raidlist_for_guild(client: discord.Client, guild_id: int):
    """
    IMMEDIATE refresh (DB fetch + embed build + discord edit), but now with hash cache
    to avoid unnecessary edits.
    """
    guild = client.get_guild(guild_id)
    if not guild:
        return

    async with await get_session() as session:
        row = await get_guild_settings(session, guild_id)
        if not row or not row.raidlist_channel_id:
            return

        ch_id = int(row.raidlist_channel_id)
        msg_id = int(row.raidlist_message_id) if row.raidlist_message_id else None
        raids = await get_open_raids_for_guild(session, guild_id)

    channel = client.get_channel(ch_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(ch_id)
        except (discord.NotFound, discord.Forbidden):
            return

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return

    embed = await build_raidlist_embed(guild, raids)
    embed_hash = _hash_embed(embed)

    # ✅ If we have a cached hash AND message exists, skip edit when unchanged
    cached = _LAST_EMBED_HASH.get(guild_id)

    try:
        if msg_id:
            msg = await channel.fetch_message(msg_id)

            # If unchanged, do nothing (big rate-limit saver)
            if cached == embed_hash:
                return

            await msg.edit(embed=embed, content=None)
            _LAST_EMBED_HASH[guild_id] = embed_hash
            return
    except (discord.NotFound, discord.Forbidden):
        # message missing / no access -> recreate
        pass

    # Create message if missing
    try:
        msg = await channel.send(embed=embed)
        _LAST_EMBED_HASH[guild_id] = embed_hash

        async with await get_session() as session:
            row = await get_guild_settings(session, guild_id)
            if row:
                row.raidlist_message_id = msg.id
                await session.commit()
    except discord.Forbidden:
        return


async def schedule_raidlist_refresh(client: discord.Client, guild_id: int) -> None:
    """
    Debounced refresh trigger (fast).
    Uses client.raidlist_updater if present; otherwise does immediate refresh.
    """
    updater = getattr(client, "raidlist_updater", None)
    if updater:
        await updater.mark_dirty(guild_id)
    else:
        await refresh_raidlist_for_guild(client, guild_id)


async def force_raidlist_refresh(client: discord.Client, guild_id: int) -> None:
    """
    Immediate refresh trigger (for /raidlist, settings save, startup).
    """
    updater = getattr(client, "raidlist_updater", None)
    if updater:
        await updater.force_update(guild_id)
    else:
        await refresh_raidlist_for_guild(client, guild_id)


async def refresh_raidlists_for_all_guilds(client: discord.Client):
    """
    Startup refresh for all guilds that have raidlist_channel configured.
    """
    async with await get_session() as session:
        res = await session.execute(
            select(GuildSettings.guild_id).where(GuildSettings.raidlist_channel_id.is_not(None))
        )
        guild_ids = [gid for (gid,) in res.all()]

    for gid in guild_ids:
        await force_raidlist_refresh(client, gid)

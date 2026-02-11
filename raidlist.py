# raidlist.py
from __future__ import annotations

import discord
from sqlalchemy import select

from db import get_session
from models import GuildSettings, Raid
from helpers import raid_jump_url, get_guild_settings


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
    IMMEDIATE refresh (does DB fetch + discord edit). Keep this as the source of truth.
    The debounced updater will call this function.
    """
    guild = client.get_guild(guild_id)
    if not guild:
        return

    async with await get_session() as session:
        row = await get_guild_settings(session, guild_id)
        if not row or not row.raidlist_channel_id:
            return
        ch_id = row.raidlist_channel_id
        msg_id = row.raidlist_message_id
        raids = await get_open_raids_for_guild(session, guild_id)

    channel = client.get_channel(ch_id)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return

    embed = await build_raidlist_embed(guild, raids)

    try:
        if msg_id:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed, content=None)
            return
    except (discord.NotFound, discord.Forbidden):
        pass

    try:
        msg = await channel.send(embed=embed)
        async with await get_session() as session:
            row = await get_guild_settings(session, guild_id)
            if row:
                row.raidlist_message_id = msg.id
                await session.commit()
    except discord.Forbidden:
        pass


async def schedule_raidlist_refresh(client: discord.Client, guild_id: int) -> None:
    """
    Debounced refresh trigger (fast). Uses client.raidlist_updater if present, else immediate.
    """
    updater = getattr(client, "raidlist_updater", None)
    if updater:
        await updater.mark_dirty(guild_id)
    else:
        await refresh_raidlist_for_guild(client, guild_id)


async def force_raidlist_refresh(client: discord.Client, guild_id: int) -> None:
    """
    Immediate refresh trigger (used for /raidlist, settings save, startup).
    """
    updater = getattr(client, "raidlist_updater", None)
    if updater:
        await updater.force_update(guild_id)
    else:
        await refresh_raidlist_for_guild(client, guild_id)


async def refresh_raidlists_for_all_guilds(client: discord.Client):
    """
    Startup refresh: do an immediate refresh for all guilds that have raidlist_channel configured.
    """
    async with await get_session() as session:
        res = await session.execute(
            select(GuildSettings.guild_id).where(GuildSettings.raidlist_channel_id.is_not(None))
        )
        guild_ids = [gid for (gid,) in res.all()]

    for gid in guild_ids:
        await force_raidlist_refresh(client, gid)

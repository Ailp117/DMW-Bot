from __future__ import annotations

import hashlib
import json

import discord
from sqlalchemy import select

from config import LOG_GUILD_ID, RAIDLIST_DEBUG_CHANNEL_ID
from db import session_scope
from models import DebugMirrorCache, GuildSettings, Raid

_LAST_HASH: dict[int, str] = {}


def _hash_embed(embed: discord.Embed) -> str:
    payload = json.dumps(embed.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jump(guild_id: int, channel_id: int, message_id: int | None) -> str:
    if not message_id:
        return "`(noch kein link)`"
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _debug_cache_key_for_raidlist(guild_id: int) -> str:
    return f"raidlist:{guild_id}:0"


async def _load_debug_cache_entry(cache_key: str) -> DebugMirrorCache | None:
    async with session_scope() as session:
        return await session.get(DebugMirrorCache, cache_key)


async def _upsert_debug_cache_entry(
    cache_key: str,
    *,
    kind: str,
    guild_id: int,
    raid_id: int | None,
    message_id: int,
    payload_hash: str,
) -> None:
    async with session_scope() as session:
        row = await session.get(DebugMirrorCache, cache_key)
        if row is None:
            row = DebugMirrorCache(
                cache_key=cache_key,
                kind=kind,
                guild_id=guild_id,
                raid_id=raid_id,
                message_id=message_id,
                payload_hash=payload_hash,
            )
            session.add(row)
            return

        row.message_id = message_id
        row.payload_hash = payload_hash


async def _mirror_raidlist_debug_embed(client: discord.Client, guild: discord.Guild, raid_embed: discord.Embed) -> None:
    if guild.id == LOG_GUILD_ID or not RAIDLIST_DEBUG_CHANNEL_ID:
        return

    channel = client.get_channel(RAIDLIST_DEBUG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(RAIDLIST_DEBUG_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden):
            return

    if not hasattr(channel, "send"):
        return

    debug_embed = discord.Embed(
        title=f"🧪 Raidlist Debug | {guild.name}",
        description=f"Guild `{guild.id}`",
        color=discord.Color.blurple(),
    )
    for field in raid_embed.fields:
        debug_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    debug_embed.set_footer(text="Debug-Spiegelung (ohne Debug-Server).")

    debug_hash = _hash_embed(debug_embed)
    cache_key = _debug_cache_key_for_raidlist(guild.id)
    cached = await _load_debug_cache_entry(cache_key)
    if cached is not None and cached.payload_hash == debug_hash:
        return

    if cached is not None and cached.message_id:
        try:
            msg = await channel.fetch_message(int(cached.message_id))
            await msg.edit(embed=debug_embed, content=None)
            await _upsert_debug_cache_entry(
                cache_key,
                kind="raidlist",
                guild_id=guild.id,
                raid_id=None,
                message_id=msg.id,
                payload_hash=debug_hash,
            )
            return
        except (discord.NotFound, discord.Forbidden):
            pass

    msg = await channel.send(embed=debug_embed)
    await _upsert_debug_cache_entry(
        cache_key,
        kind="raidlist",
        guild_id=guild.id,
        raid_id=None,
        message_id=msg.id,
        payload_hash=debug_hash,
    )


async def refresh_raidlist_for_guild(client: discord.Client, guild_id: int) -> None:
    guild = client.get_guild(guild_id)
    if not guild:
        return

    async with session_scope() as session:
        s = await session.get(GuildSettings, guild_id)
        if not s or not s.raidlist_channel_id:
            return

        raids = (
            await session.execute(
                select(Raid)
                .where(Raid.guild_id == guild_id, Raid.status == "open")
                .order_by(Raid.created_at.desc())
            )
        ).scalars().all()

        raidlist_channel_id = int(s.raidlist_channel_id)
        raidlist_message_id = int(s.raidlist_message_id) if s.raidlist_message_id else None

    e = discord.Embed(title="📌 Offene Raids", description=f"Server: **{guild.name}**")
    if not raids:
        e.add_field(name="Status", value="Keine offenen Raids.", inline=False)
    else:
        lines = []
        for r in raids[:25]:
            lines.append(
                f"• **{r.dungeon}** | 🆔 `{r.id}` | Min/Slot `{r.min_players}` | {_jump(r.guild_id, r.channel_id, r.message_id)}"
            )
        e.add_field(name="Liste", value="\n".join(lines)[:1024], inline=False)
    e.set_footer(text="Auto-Update aktiv.")

    h = _hash_embed(e)
    if _LAST_HASH.get(guild_id) == h:
        await _mirror_raidlist_debug_embed(client, guild, e)
        return

    channel = client.get_channel(raidlist_channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(raidlist_channel_id)
        except (discord.NotFound, discord.Forbidden):
            return

    if not hasattr(channel, "send"):
        return

    if raidlist_message_id:
        try:
            msg = await channel.fetch_message(raidlist_message_id)
            await msg.edit(embed=e, content=None)
            _LAST_HASH[guild_id] = h
            await _mirror_raidlist_debug_embed(client, guild, e)
            return
        except (discord.NotFound, discord.Forbidden):
            pass

    msg = await channel.send(embed=e)
    async with session_scope() as session:
        s2 = await session.get(GuildSettings, guild_id)
        if s2:
            s2.raidlist_message_id = msg.id
    _LAST_HASH[guild_id] = h
    await _mirror_raidlist_debug_embed(client, guild, e)


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

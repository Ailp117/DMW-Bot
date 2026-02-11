import re
import asyncio
import discord
from dataclasses import dataclass
from collections import Counter, defaultdict
from typing import Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import TEMP_DELETE_SECONDS
from models import Raid, RaidOption, RaidVote, RaidPostedSlot, GuildSettings

async def _delete_after(msg: discord.Message, seconds: int):
    try:
        await asyncio.sleep(seconds)
        await msg.delete()
    except Exception:
        pass

async def send_temp(interaction: discord.Interaction, content: str, *, seconds: int = TEMP_DELETE_SECONDS):
    try:
        if interaction.channel and isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            msg = await interaction.channel.send(content)
            asyncio.create_task(_delete_after(msg, seconds))
            return
    except Exception:
        pass

    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)

def split_csv(value: str) -> list[str]:
    raw = re.split(r"[,\n;]+", value.strip())
    parts = [p.strip() for p in raw if p and p.strip()]
    seen = set()
    out = []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out

@dataclass
class RaidSummary:
    top_day: Optional[str]
    top_time: Optional[str]
    active_participants: list[int]
    day_map: dict[str, list[int]]
    time_map: dict[str, list[int]]

async def get_guild_settings(session: AsyncSession, guild_id: int) -> Optional[GuildSettings]:
    return await session.get(GuildSettings, guild_id)

async def get_raid(session: AsyncSession, raid_id: int) -> Optional[Raid]:
    res = await session.execute(select(Raid).where(Raid.id == raid_id))
    return res.scalar_one_or_none()

async def get_options(session: AsyncSession, raid_id: int) -> tuple[list[str], list[str]]:
    res = await session.execute(select(RaidOption).where(RaidOption.raid_id == raid_id))
    rows = res.scalars().all()
    return [r.label for r in rows if r.kind == "day"], [r.label for r in rows if r.kind == "time"]

async def toggle_vote(session: AsyncSession, raid_id: int, kind: str, option_label: str, user_id: int) -> None:
    res = await session.execute(
        select(RaidVote).where(
            RaidVote.raid_id == raid_id,
            RaidVote.kind == kind,
            RaidVote.option_label == option_label,
            RaidVote.user_id == user_id,
        )
    )
    existing = res.scalar_one_or_none()
    if existing:
        await session.execute(delete(RaidVote).where(RaidVote.id == existing.id))
    else:
        session.add(RaidVote(raid_id=raid_id, kind=kind, option_label=option_label, user_id=user_id))
    await session.commit()

async def build_summary(session: AsyncSession, raid_id: int) -> RaidSummary:
    res = await session.execute(select(RaidVote).where(RaidVote.raid_id == raid_id))
    votes = res.scalars().all()

    day_users = defaultdict(list)
    time_users = defaultdict(list)
    user_days = defaultdict(set)
    user_times = defaultdict(set)

    for v in votes:
        if v.kind == "day":
            day_users[v.option_label].append(v.user_id)
            user_days[v.user_id].add(v.option_label)
        else:
            time_users[v.option_label].append(v.user_id)
            user_times[v.user_id].add(v.option_label)

    active = [uid for uid in set(user_days) | set(user_times) if user_days[uid] and user_times[uid]]

    top_day = Counter({k: len(set(v)) for k, v in day_users.items()}).most_common(1)[0][0] if day_users else None
    top_time = Counter({k: len(set(v)) for k, v in time_users.items()}).most_common(1)[0][0] if time_users else None

    return RaidSummary(
        top_day=top_day,
        top_time=top_time,
        active_participants=sorted(set(active)),
        day_map={k: sorted(set(v)) for k, v in day_users.items()},
        time_map={k: sorted(set(v)) for k, v in time_users.items()},
    )

async def set_raid_message_id(session: AsyncSession, raid_id: int, message_id: int) -> None:
    await session.execute(update(Raid).where(Raid.id == raid_id).values(message_id=message_id))
    await session.commit()

async def delete_raid_completely(session: AsyncSession, raid_id: int) -> None:
    await session.execute(delete(Raid).where(Raid.id == raid_id))
    await session.commit()

def short_list(mentions: list[str], limit: int = 60) -> str:
    if not mentions:
        return "—"
    if len(mentions) <= limit:
        return ", ".join(mentions)
    return ", ".join(mentions[:limit]) + f" … (+{len(mentions) - limit})"

async def build_embed_for_raid(raid: Raid, summary: RaidSummary) -> discord.Embed:
    e = discord.Embed(title="DMW Raid Planer", description=f"**Dungeon:** {raid.dungeon}\n**Status:** {raid.status}")
    e.add_field(name="Top Tag", value=summary.top_day or "—", inline=True)
    e.add_field(name="Top Uhrzeit", value=summary.top_time or "—", inline=True)
    e.add_field(name="Aktive Teilnehmer (mind. Tag+Zeit)", value=f"{len(summary.active_participants)}", inline=False)

    def mention(uid: int) -> str:
        return f"<@{uid}>"

    if summary.day_map:
        lines = []
        for opt, uids in sorted(summary.day_map.items(), key=lambda x: (-len(x[1]), x[0].lower())):
            lines.append(f"**{opt}** ({len(uids)}): {short_list([mention(u) for u in uids], limit=40)}")
        e.add_field(name="Tage – Votes", value="\n".join(lines)[:1024], inline=False)

    if summary.time_map:
        lines = []
        for opt, uids in sorted(summary.time_map.items(), key=lambda x: (-len(x[1]), x[0].lower())):
            lines.append(f"**{opt}** ({len(uids)}): {short_list([mention(u) for u in uids], limit=40)}")
        e.add_field(name="Uhrzeiten – Votes", value="\n".join(lines)[:1024], inline=False)

    e.set_footer(text=f"Raid-ID: {raid.id} | Min pro Slot: {raid.min_players}")
    return e

def raid_jump_url(raid: Raid) -> str:
    if not raid.message_id:
        return "—"
    return f"https://discord.com/channels/{raid.guild_id}/{raid.channel_id}/{raid.message_id}"

async def get_users_for_day(session: AsyncSession, raid_id: int, day_label: str) -> set[int]:
    res = await session.execute(
        select(RaidVote.user_id).where(
            RaidVote.raid_id == raid_id, RaidVote.kind == "day", RaidVote.option_label == day_label
        )
    )
    return set(res.scalars().all())

async def get_users_for_time(session: AsyncSession, raid_id: int, time_label: str) -> set[int]:
    res = await session.execute(
        select(RaidVote.user_id).where(
            RaidVote.raid_id == raid_id, RaidVote.kind == "time", RaidVote.option_label == time_label
        )
    )
    return set(res.scalars().all())

async def get_posted_slot_row(session: AsyncSession, raid_id: int, day_label: str, time_label: str) -> Optional[RaidPostedSlot]:
    res = await session.execute(
        select(RaidPostedSlot).where(
            RaidPostedSlot.raid_id == raid_id,
            RaidPostedSlot.day_label == day_label,
            RaidPostedSlot.time_label == time_label,
        )
    )
    return res.scalar_one_or_none()

async def upsert_posted_slot_message(session: AsyncSession, raid_id: int, day_label: str, time_label: str, channel_id: int, message_id: int):
    row = await get_posted_slot_row(session, raid_id, day_label, time_label)
    if row:
        row.channel_id = channel_id
        row.message_id = message_id
    else:
        session.add(
            RaidPostedSlot(
                raid_id=raid_id,
                day_label=day_label,
                time_label=time_label,
                channel_id=channel_id,
                message_id=message_id,
            )
        )
    await session.commit()

async def get_all_posted_slots(session: AsyncSession, raid_id: int) -> list[RaidPostedSlot]:
    from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Raid, RaidOption
from helpers import split_csv  # falls split_csv in helpers.py ist, sonst diese Zeile löschen

async def create_raid(
    session: AsyncSession,
    guild_id: int,
    planner_channel_id: int,
    creator_id: int,
    dungeon: str,
    days_csv: str,
    times_csv: str,
    min_players: int,
) -> Raid:
    """
    Erstellt einen neuen Raid + Optionen (Tage/Uhrzeiten) in der DB.
    """
    raid = Raid(
        guild_id=guild_id,
        channel_id=planner_channel_id,
        creator_id=creator_id,
        dungeon=dungeon,
        status="open",
        min_players=min_players,
        participants_posted=False,
    )
    session.add(raid)
    await session.flush()  # damit raid.id verfügbar ist

    days = split_csv(days_csv)
    times = split_csv(times_csv)

    # Optionen speichern
    for d in days:
        session.add(RaidOption(raid_id=raid.id, kind="day", label=d))
    for t in times:
        session.add(RaidOption(raid_id=raid.id, kind="time", label=t))

    await session.commit()
    await session.refresh(raid)
    return raid

    res = await session.execute(select(RaidPostedSlot).where(RaidPostedSlot.raid_id == raid_id))
    return res.scalars().all()


from __future__ import annotations
import re
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import GuildSettings, Raid, RaidOption, RaidVote, RaidPostedSlot, Dungeon, UserLevel

def normalize_list(text: str) -> list[str]:
    parts = re.split(r"[,;\n]+", (text or "").strip())
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if s and s not in out:
            out.append(s)
    return out[:25]

async def get_settings(session: AsyncSession, guild_id: int, guild_name: str | None = None) -> GuildSettings:
    s = await session.get(GuildSettings, guild_id)
    if not s:
        s = GuildSettings(guild_id=guild_id, guild_name=guild_name)
        session.add(s)
        await session.flush()
    elif guild_name and s.guild_name != guild_name:
        s.guild_name = guild_name
    return s

async def get_active_dungeons(session: AsyncSession) -> list[Dungeon]:
    rows = (await session.execute(
        select(Dungeon).where(Dungeon.is_active.is_(True)).order_by(Dungeon.sort_order.asc(), Dungeon.name.asc())
    )).scalars().all()
    return rows

async def create_raid(session: AsyncSession, guild_id: int, planner_channel_id: int, creator_id: int, dungeon: str, days: list[str], times: list[str], min_players: int) -> Raid:
    next_display_id = (await session.execute(
        select(func.coalesce(func.max(Raid.display_id), 0) + 1).where(Raid.guild_id == guild_id)
    )).scalar_one()

    raid = Raid(
        display_id=int(next_display_id),
        guild_id=guild_id,
        channel_id=planner_channel_id,
        creator_id=creator_id,
        dungeon=dungeon,
        status="open",
        min_players=min_players,
        participants_posted=False,
        temp_role_created=False,
    )
    session.add(raid)
    await session.flush()

    # bulk add options (fast)
    session.add_all([RaidOption(raid_id=raid.id, kind="day", label=d) for d in days])
    session.add_all([RaidOption(raid_id=raid.id, kind="time", label=t) for t in times])
    await session.flush()
    return raid

async def get_raid(session: AsyncSession, raid_id: int) -> Raid | None:
    return await session.get(Raid, raid_id)

async def get_options(session: AsyncSession, raid_id: int) -> tuple[list[str], list[str]]:
    rows = (await session.execute(select(RaidOption).where(RaidOption.raid_id == raid_id))).scalars().all()
    days = [r.label for r in rows if r.kind == "day"]
    times = [r.label for r in rows if r.kind == "time"]
    return days, times

async def toggle_vote(session: AsyncSession, raid_id: int, kind: str, label: str, user_id: int) -> None:
    existing = (await session.execute(
        select(RaidVote).where(
            RaidVote.raid_id == raid_id,
            RaidVote.kind == kind,
            RaidVote.option_label == label,
            RaidVote.user_id == user_id
        )
    )).scalar_one_or_none()

    if existing:
        await session.delete(existing)
    else:
        session.add(RaidVote(raid_id=raid_id, kind=kind, option_label=label, user_id=user_id))

async def vote_counts(session: AsyncSession, raid_id: int) -> dict[str, dict[str, int]]:
    rows = (await session.execute(select(RaidVote).where(RaidVote.raid_id == raid_id))).scalars().all()
    out: dict[str, dict[str, int]] = {"day": {}, "time": {}}
    for v in rows:
        out[v.kind][v.option_label] = out[v.kind].get(v.option_label, 0) + 1
    return out

async def vote_user_sets(session: AsyncSession, raid_id: int) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    rows = (await session.execute(select(RaidVote).where(RaidVote.raid_id == raid_id))).scalars().all()
    day_users: dict[str, set[int]] = {}
    time_users: dict[str, set[int]] = {}

    for vote in rows:
        target = day_users if vote.kind == "day" else time_users
        users = target.setdefault(vote.option_label, set())
        users.add(int(vote.user_id))

    return day_users, time_users

async def posted_slot_map(session: AsyncSession, raid_id: int) -> dict[tuple[str, str], RaidPostedSlot]:
    rows = (await session.execute(
        select(RaidPostedSlot).where(RaidPostedSlot.raid_id == raid_id)
    )).scalars().all()
    return {(row.day_label, row.time_label): row for row in rows}

async def slot_users(session: AsyncSession, raid_id: int, day_label: str, time_label: str) -> list[int]:
    day = set((await session.execute(
        select(RaidVote.user_id).where(
            RaidVote.raid_id == raid_id,
            RaidVote.kind == "day",
            RaidVote.option_label == day_label
        )
    )).scalars().all())
    tim = set((await session.execute(
        select(RaidVote.user_id).where(
            RaidVote.raid_id == raid_id,
            RaidVote.kind == "time",
            RaidVote.option_label == time_label
        )
    )).scalars().all())
    return sorted(day.intersection(tim))

async def get_posted_slot(session: AsyncSession, raid_id: int, day_label: str, time_label: str) -> RaidPostedSlot | None:
    return (await session.execute(
        select(RaidPostedSlot).where(
            RaidPostedSlot.raid_id == raid_id,
            RaidPostedSlot.day_label == day_label,
            RaidPostedSlot.time_label == time_label
        )
    )).scalar_one_or_none()

async def upsert_posted_slot(session: AsyncSession, raid_id: int, day_label: str, time_label: str, channel_id: int, message_id: int) -> None:
    row = await get_posted_slot(session, raid_id, day_label, time_label)
    if row:
        row.channel_id = channel_id
        row.message_id = message_id
    else:
        session.add(RaidPostedSlot(
            raid_id=raid_id,
            day_label=day_label,
            time_label=time_label,
            channel_id=channel_id,
            message_id=message_id,
        ))


async def purge_guild_data(session: AsyncSession, guild_id: int) -> dict[str, int]:
    deleted_raids = await session.execute(delete(Raid).where(Raid.guild_id == guild_id))
    deleted_user_levels = await session.execute(delete(UserLevel).where(UserLevel.guild_id == guild_id))
    deleted_settings = await session.execute(delete(GuildSettings).where(GuildSettings.guild_id == guild_id))

    return {
        "raids": deleted_raids.rowcount or 0,
        "user_levels": deleted_user_levels.rowcount or 0,
        "guild_settings": deleted_settings.rowcount or 0,
    }

async def delete_raid_cascade(session: AsyncSession, raid_id: int) -> None:
    r = await session.get(Raid, raid_id)
    if r:
        await session.delete(r)

def short_list(mentions: list[str], limit: int = 50) -> str:
    if not mentions:
        return "—"
    if len(mentions) <= limit:
        return "\n".join(mentions)
    return "\n".join(mentions[:limit]) + f"\n… +{len(mentions)-limit} weitere"

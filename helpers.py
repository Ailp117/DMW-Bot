from __future__ import annotations
import re
from sqlalchemy import select, delete, func
import json
from sqlalchemy.ext.asyncio import AsyncSession

from models import GuildSettings, Raid, RaidOption, RaidVote, RaidPostedSlot, Dungeon, UserLevel, RaidTemplate, RaidAttendance

AUTO_DUNGEON_TEMPLATE_NAME = "_auto_dungeon_default"

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




async def get_template_by_name(session: AsyncSession, guild_id: int, dungeon_id: int, template_name: str) -> RaidTemplate | None:
    return (await session.execute(
        select(RaidTemplate).where(
            RaidTemplate.guild_id == guild_id,
            RaidTemplate.dungeon_id == dungeon_id,
            RaidTemplate.template_name == template_name,
        )
    )).scalar_one_or_none()


async def list_templates(session: AsyncSession, guild_id: int, dungeon_id: int | None = None) -> list[RaidTemplate]:
    stmt = select(RaidTemplate).where(RaidTemplate.guild_id == guild_id)
    if dungeon_id is not None:
        stmt = stmt.where(RaidTemplate.dungeon_id == dungeon_id)
    stmt = stmt.order_by(RaidTemplate.dungeon_id.asc(), RaidTemplate.template_name.asc())
    return (await session.execute(stmt)).scalars().all()


def dump_template_data(days: list[str], times: list[str], min_players: int) -> str:
    return json.dumps({"days": days, "times": times, "min_players": min_players}, ensure_ascii=False)


def load_template_data(template_data: str) -> tuple[list[str], list[str], int]:
    payload = json.loads(template_data or "{}")
    days = normalize_list(",".join(payload.get("days") or []))
    times = normalize_list(",".join(payload.get("times") or []))
    try:
        min_players = max(0, int(payload.get("min_players", 0)))
    except (TypeError, ValueError):
        min_players = 0
    return days, times, min_players


def compute_qualified_slot_users(
    days: list[str],
    times: list[str],
    day_users: dict[str, set[int]],
    time_users: dict[str, set[int]],
    threshold: int,
) -> tuple[dict[tuple[str, str], list[int]], set[int]]:
    qualified_slots: dict[tuple[str, str], list[int]] = {}
    all_users: set[int] = set()

    for day in days:
        for time in times:
            users = sorted(day_users.get(day, set()).intersection(time_users.get(time, set())))
            if len(users) < threshold:
                continue
            qualified_slots[(day, time)] = users
            all_users.update(users)

    return qualified_slots, all_users




async def upsert_auto_dungeon_template(
    session: AsyncSession,
    *,
    guild_id: int,
    dungeon_id: int,
    days: list[str],
    times: list[str],
    min_players: int,
) -> RaidTemplate:
    """Create/update the per-guild per-dungeon auto template used as planning default."""
    row = await get_template_by_name(session, guild_id, dungeon_id, AUTO_DUNGEON_TEMPLATE_NAME)
    payload = dump_template_data(days, times, min_players)

    if row is None:
        row = RaidTemplate(
            guild_id=guild_id,
            dungeon_id=dungeon_id,
            template_name=AUTO_DUNGEON_TEMPLATE_NAME,
            template_data=payload,
        )
        session.add(row)
        await session.flush()
        return row

    row.template_data = payload
    return row

async def create_attendance_snapshot(
    session: AsyncSession,
    *,
    guild_id: int,
    raid_display_id: int,
    dungeon: str,
    user_ids: set[int],
) -> int:
    existing_user_ids = set((await session.execute(
        select(RaidAttendance.user_id).where(
            RaidAttendance.guild_id == guild_id,
            RaidAttendance.raid_display_id == raid_display_id,
        )
    )).scalars().all())

    new_user_ids = sorted(set(user_ids) - {int(uid) for uid in existing_user_ids})
    if not new_user_ids:
        return 0

    session.add_all([
        RaidAttendance(
            guild_id=guild_id,
            raid_display_id=raid_display_id,
            dungeon=dungeon,
            user_id=user_id,
            status="pending",
        )
        for user_id in new_user_ids
    ])
    return len(new_user_ids)

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

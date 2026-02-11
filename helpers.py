from __future__ import annotations

import re
import discord
from sqlalchemy import select, delete

from db import get_session
from models import GuildSettings, Raid, RaidOption, RaidVote, RaidPostedSlot


def normalize_list(text: str) -> list[str]:
    parts = re.split(r"[,;\n]+", (text or "").strip())
    out = []
    for p in parts:
        s = p.strip()
        if s and s not in out:
            out.append(s)
    return out[:25]


async def get_or_create_settings(guild_id: int) -> GuildSettings:
    async with await get_session() as session:
        s = await session.get(GuildSettings, guild_id)
        if not s:
            s = GuildSettings(guild_id=guild_id)
            session.add(s)
            await session.commit()
        return s


async def set_settings(guild_id: int, planner: int | None, participants: int | None, raidlist: int | None):
    async with await get_session() as session:
        s = await session.get(GuildSettings, guild_id)
        if not s:
            s = GuildSettings(guild_id=guild_id)
            session.add(s)
        if planner is not None:
            s.planner_channel_id = planner
        if participants is not None:
            s.participants_channel_id = participants
        if raidlist is not None:
            if s.raidlist_channel_id != raidlist:
                s.raidlist_channel_id = raidlist
                s.raidlist_message_id = None
        await session.commit()


async def create_raid(
    guild_id: int,
    planner_channel_id: int,
    creator_id: int,
    dungeon: str,
    days: list[str],
    times: list[str],
    min_players: int,
) -> Raid:
    async with await get_session() as session:
        raid = Raid(
            guild_id=guild_id,
            channel_id=planner_channel_id,
            creator_id=creator_id,
            dungeon=dungeon,
            status="open",
            min_players=min_players,
        )
        session.add(raid)
        await session.flush()

        for d in days:
            session.add(RaidOption(raid_id=raid.id, kind="day", label=d))
        for t in times:
            session.add(RaidOption(raid_id=raid.id, kind="time", label=t))

        await session.commit()
        return raid


async def set_raid_message_id(raid_id: int, message_id: int):
    async with await get_session() as session:
        r = await session.get(Raid, raid_id)
        if r:
            r.message_id = message_id
            await session.commit()


async def get_raid(raid_id: int) -> Raid | None:
    async with await get_session() as session:
        return await session.get(Raid, raid_id)


async def get_options(raid_id: int) -> tuple[list[str], list[str]]:
    async with await get_session() as session:
        rows = (await session.execute(select(RaidOption).where(RaidOption.raid_id == raid_id))).scalars().all()
    days = [r.label for r in rows if r.kind == "day"]
    times = [r.label for r in rows if r.kind == "time"]
    return days, times


async def toggle_vote(raid_id: int, kind: str, label: str, user_id: int):
    async with await get_session() as session:
        exists = (await session.execute(
            select(RaidVote).where(
                RaidVote.raid_id == raid_id,
                RaidVote.kind == kind,
                RaidVote.option_label == label,
                RaidVote.user_id == user_id,
            )
        )).scalar_one_or_none()

        if exists:
            await session.delete(exists)
        else:
            session.add(RaidVote(raid_id=raid_id, kind=kind, option_label=label, user_id=user_id))
        await session.commit()


async def vote_counts(raid_id: int) -> dict[str, dict[str, int]]:
    async with await get_session() as session:
        rows = (await session.execute(select(RaidVote).where(RaidVote.raid_id == raid_id))).scalars().all()
    out: dict[str, dict[str, int]] = {"day": {}, "time": {}}
    for v in rows:
        out[v.kind][v.option_label] = out[v.kind].get(v.option_label, 0) + 1
    return out


async def get_slot_user_ids(raid_id: int, day_label: str, time_label: str) -> list[int]:
    """
    Slot: user hat day vote + time vote
    """
    async with await get_session() as session:
        day_users = set((await session.execute(
            select(RaidVote.user_id).where(RaidVote.raid_id == raid_id, RaidVote.kind == "day", RaidVote.option_label == day_label)
        )).scalars().all())
        time_users = set((await session.execute(
            select(RaidVote.user_id).where(RaidVote.raid_id == raid_id, RaidVote.kind == "time", RaidVote.option_label == time_label)
        )).scalars().all())
    return sorted(day_users.intersection(time_users))


async def get_posted_slot(raid_id: int, day_label: str, time_label: str) -> RaidPostedSlot | None:
    async with await get_session() as session:
        return (await session.execute(
            select(RaidPostedSlot).where(
                RaidPostedSlot.raid_id == raid_id,
                RaidPostedSlot.day_label == day_label,
                RaidPostedSlot.time_label == time_label,
            )
        )).scalar_one_or_none()


async def upsert_posted_slot(raid_id: int, day_label: str, time_label: str, channel_id: int, message_id: int):
    async with await get_session() as session:
        row = (await session.execute(
            select(RaidPostedSlot).where(
                RaidPostedSlot.raid_id == raid_id,
                RaidPostedSlot.day_label == day_label,
                RaidPostedSlot.time_label == time_label,
            )
        )).scalar_one_or_none()
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
        await session.commit()


async def delete_raid_completely(raid_id: int):
    async with await get_session() as session:
        # CASCADE löscht children; wir löschen Raid explizit:
        r = await session.get(Raid, raid_id)
        if r:
            await session.delete(r)
            await session.commit()


async def short_list(items: list[str], limit: int = 40) -> str:
    if not items:
        return "—"
    if len(items) <= limit:
        return "\n".join(items)
    return "\n".join(items[:limit]) + f"\n… +{len(items) - limit} weitere"


async def send_temp(interaction: discord.Interaction, text: str, seconds: int = 30):
    await interaction.followup.send(text, ephemeral=True)

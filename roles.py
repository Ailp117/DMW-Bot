from __future__ import annotations

import discord
from sqlalchemy import select

from db import get_session
from models import Raid, RaidVote


def role_name_for_dungeon(dungeon: str) -> str:
    return f"DMW Raid: {dungeon}"


async def ensure_temp_role(guild: discord.Guild, dungeon: str) -> discord.Role | None:
    name = role_name_for_dungeon(dungeon)
    role = discord.utils.get(guild.roles, name=name)
    if role:
        return role
    try:
        return await guild.create_role(name=name, mentionable=True, reason="DMW Raid Planner temp role")
    except discord.Forbidden:
        return None


async def cleanup_temp_role(guild: discord.Guild, dungeon: str) -> None:
    role = discord.utils.get(guild.roles, name=role_name_for_dungeon(dungeon))
    if not role:
        return
    try:
        # entfernen + löschen
        for m in list(role.members):
            try:
                await m.remove_roles(role, reason="DMW Raid finished")
            except discord.Forbidden:
                pass
        await role.delete(reason="DMW Raid finished")
    except discord.Forbidden:
        pass


async def compute_role_members_for_raid(raid_id: int, min_players: int) -> set[int]:
    """
    Rollen-Logik: Role bekommt Nutzer, die in mindestens einem Slot (day∩time) threshold erreichen.
    Minimal gehalten: wer irgendeine day vote + irgendeine time vote hat, kommt in role
    (Du kannst das später präziser machen.)
    """
    async with await get_session() as session:
        days = (await session.execute(select(RaidVote.user_id).where(RaidVote.raid_id == raid_id, RaidVote.kind == "day"))).scalars().all()
        times = (await session.execute(select(RaidVote.user_id).where(RaidVote.raid_id == raid_id, RaidVote.kind == "time"))).scalars().all()
    return set(days).intersection(set(times))


async def sync_role_membership(guild: discord.Guild, role: discord.Role, desired_user_ids: set[int]) -> None:
    current = {m.id for m in role.members}
    add = desired_user_ids - current
    rem = current - desired_user_ids

    for uid in add:
        m = guild.get_member(uid)
        if m:
            try:
                await m.add_roles(role, reason="DMW Raid role sync")
            except discord.Forbidden:
                pass

    for uid in rem:
        m = guild.get_member(uid)
        if m:
            try:
                await m.remove_roles(role, reason="DMW Raid role sync")
            except discord.Forbidden:
                pass

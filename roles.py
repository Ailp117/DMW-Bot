import discord
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Raid
from helpers import get_options, get_users_for_day, get_users_for_time

def temp_role_name(raid: Raid) -> str:
    return f"{raid.dungeon} [Raid {raid.id}]"

async def ensure_temp_role_for_raid(session: AsyncSession, guild: discord.Guild, raid: Raid) -> Optional[discord.Role]:
    if raid.temp_role_id:
        role = guild.get_role(raid.temp_role_id)
        if role:
            return role

    role_name = temp_role_name(raid)
    existing = discord.utils.get(guild.roles, name=role_name)
    if existing:
        await session.execute(update(Raid).where(Raid.id == raid.id).values(temp_role_id=existing.id, temp_role_created=False))
        await session.commit()
        return existing

    try:
        role = await guild.create_role(name=role_name, mentionable=True, reason=f"Temp role for raid {raid.id}")
    except discord.Forbidden:
        return None

    await session.execute(update(Raid).where(Raid.id == raid.id).values(temp_role_id=role.id, temp_role_created=True))
    await session.commit()
    return role

async def compute_desired_role_users_for_raid(session: AsyncSession, raid_id: int, min_players: int) -> set[int]:
    days, times = await get_options(session, raid_id)
    desired: set[int] = set()
    for d in days:
        day_users = await get_users_for_day(session, raid_id, d)
        if not day_users:
            continue
        for t in times:
            time_users = await get_users_for_time(session, raid_id, t)
            if not time_users:
                continue
            slot_users = set(day_users.intersection(time_users))
            if len(slot_users) >= min_players:
                desired |= slot_users
    return desired

async def sync_role_membership(guild: discord.Guild, role: discord.Role, desired_user_ids: set[int]) -> None:
    current_ids = {m.id for m in role.members}
    to_add = desired_user_ids - current_ids
    to_remove = current_ids - desired_user_ids

    for uid in to_add:
        member = guild.get_member(uid)
        if member:
            try:
                await member.add_roles(role, reason="Raid slot reached min players")
            except discord.Forbidden:
                pass

    for uid in to_remove:
        member = guild.get_member(uid)
        if member:
            try:
                await member.remove_roles(role, reason="Raid slot updated / no longer qualifies")
            except discord.Forbidden:
                pass

async def cleanup_temp_role(session: AsyncSession, guild: discord.Guild, raid: Raid) -> None:
    if not raid.temp_role_id:
        return
    role = guild.get_role(raid.temp_role_id)
    if not role:
        return

    for member in list(role.members):
        try:
            await member.remove_roles(role, reason="Raid finished - cleanup temp role")
        except discord.Forbidden:
            pass

    if raid.temp_role_created:
        try:
            await role.delete(reason="Raid finished - delete temp role")
        except discord.Forbidden:
            pass

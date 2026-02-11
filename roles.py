from __future__ import annotations
import discord
from sqlalchemy.ext.asyncio import AsyncSession

from models import Raid

def role_name(dungeon: str) -> str:
    return f"DMW Raid: {dungeon}"

async def ensure_temp_role(session: AsyncSession, guild: discord.Guild, raid: Raid) -> discord.Role | None:
    # if already stored
    if raid.temp_role_id:
        role = guild.get_role(int(raid.temp_role_id))
        if role:
            return role

    # try find by name
    role = discord.utils.get(guild.roles, name=role_name(raid.dungeon))
    if role:
        raid.temp_role_id = role.id
        return role

    try:
        role = await guild.create_role(name=role_name(raid.dungeon), mentionable=True, reason="DMW Raid temp role")
        raid.temp_role_id = role.id
        raid.temp_role_created = True
        return role
    except discord.Forbidden:
        return None

async def cleanup_temp_role(session: AsyncSession, guild: discord.Guild, raid: Raid) -> None:
    if not raid.temp_role_id:
        return
    role = guild.get_role(int(raid.temp_role_id))
    if not role:
        return

    # Only delete if bot created it
    if not raid.temp_role_created:
        # just remove members
        for m in list(role.members):
            try:
                await m.remove_roles(role, reason="DMW Raid finished")
            except discord.Forbidden:
                pass
        return

    try:
        for m in list(role.members):
            try:
                await m.remove_roles(role, reason="DMW Raid finished")
            except discord.Forbidden:
                pass
        await role.delete(reason="DMW Raid finished")
    except discord.Forbidden:
        pass

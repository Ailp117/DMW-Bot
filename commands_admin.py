from discord import app_commands
import discord
from sqlalchemy import select
from db import get_session
from models import Dungeon
from helpers import send_temp

def register_admin_commands(tree: app_commands.CommandTree):
    @tree.command(name="dungeonadd", description="Fügt einen Dungeon in die DB ein (Admin).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def dungeonadd(interaction: discord.Interaction, name: str, short_code: str, sort_order: int = 0):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        short_code = short_code.strip().lower()
        name = name.strip()

        async with await get_session() as session:
            res = await session.execute(select(Dungeon).where(Dungeon.short_code == short_code))
            if res.scalar_one_or_none():
                return await send_temp(interaction, "❌ short_code existiert bereits.")
            session.add(Dungeon(name=name, short_code=short_code, is_active=True, sort_order=sort_order))
            await session.commit()

        await send_temp(interaction, f"✅ Dungeon hinzugefügt: **{name}** (`{short_code}`)")

    @tree.command(name="dungeonlist", description="Zeigt aktive Dungeons aus der DB.")
    async def dungeonlist(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        async with await get_session() as session:
            res = await session.execute(
                select(Dungeon).where(Dungeon.is_active == True).order_by(Dungeon.sort_order.asc(), Dungeon.name.asc())
            )
            dungeons = res.scalars().all()

        if not dungeons:
            return await send_temp(interaction, "Keine aktiven Dungeons gefunden.")

        text_out = "\n".join([f"• **{d.name}** (`{d.short_code}`) | order={d.sort_order}" for d in dungeons[:50]])
        await send_temp(interaction, text_out)

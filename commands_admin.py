import discord
from discord import app_commands
from sqlalchemy import select

from db import get_session
from models import Dungeon, Raid
from helpers import delete_raid_completely
from roles import cleanup_temp_role
from raidlist import schedule_raidlist_refresh


def register_admin_commands(tree: app_commands.CommandTree):

    @tree.command(name="dungeonadd", description="Dungeon hinzufügen (Admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def dungeonadd(interaction: discord.Interaction, short_code: str, name: str, sort_order: int = 0):
        await interaction.response.defer(ephemeral=True)
        async with await get_session() as session:
            exists = await session.get(Dungeon, short_code)
            if exists:
                return await interaction.followup.send("❌ short_code existiert bereits.", ephemeral=True)
            session.add(Dungeon(short_code=short_code, name=name, is_active=1, sort_order=sort_order))
            await session.commit()
        await interaction.followup.send(f"✅ Dungeon hinzugefügt: **{name}**", ephemeral=True)

    @tree.command(name="dungeonlist", description="Aktive Dungeons anzeigen")
    async def dungeonlist(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with await get_session() as session:
            rows = (await session.execute(select(Dungeon).where(Dungeon.is_active == 1).order_by(Dungeon.sort_order.asc(), Dungeon.name.asc()))).scalars().all()
        if not rows:
            return await interaction.followup.send("Keine aktiven Dungeons.", ephemeral=True)
        txt = "\n".join([f"• **{d.name}** (`{d.short_code}`)" for d in rows[:50]])
        await interaction.followup.send(txt, ephemeral=True)

    @tree.command(name="cancel_all_raids", description="❌ Alle offenen Raids abbrechen (Admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_all_raids(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        async with await get_session() as session:
            raids = (await session.execute(select(Raid).where(Raid.guild_id == interaction.guild.id, Raid.status == "open"))).scalars().all()

        count = 0
        for r in raids:
            try:
                await cleanup_temp_role(interaction.guild, r.dungeon)
            except Exception:
                pass
            try:
                await delete_raid_completely(r.id)
                count += 1
            except Exception:
                pass

        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)
        await interaction.followup.send(f"✅ {count} offene Raids gecancelt.", ephemeral=True)

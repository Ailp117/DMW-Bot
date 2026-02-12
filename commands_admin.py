import discord
from discord import app_commands
from sqlalchemy import select

from db import session_scope
from models import Dungeon, Raid
from helpers import get_active_dungeons, delete_raid_cascade
from roles import cleanup_temp_role
from raidlist import schedule_raidlist_refresh


def register_admin_commands(tree: app_commands.CommandTree):

    @tree.command(name="dungeonlist", description="Aktive Dungeons anzeigen")
    async def dungeonlist(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            rows = await get_active_dungeons(session)
        if not rows:
            return await interaction.followup.send("Keine aktiven Dungeons.", ephemeral=True)
        await interaction.followup.send("\n".join([f"• **{d.name}** (`{d.short_code}`)" for d in rows[:50]]), ephemeral=True)

    @tree.command(name="cancel_all_raids", description="❌ Alle offenen Raids abbrechen (Admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_all_raids(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        async with session_scope() as session:
            raids = (await session.execute(
                select(Raid).where(Raid.guild_id == interaction.guild.id, Raid.status == "open")
            )).scalars().all()

        count = 0
        async with session_scope() as session:
            for r in raids:
                raid = await session.get(Raid, r.id)
                if not raid:
                    continue
                try:
                    await cleanup_temp_role(session, interaction.guild, raid)
                except Exception:
                    pass
                await delete_raid_cascade(session, raid.id)
                count += 1

        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)
        await interaction.followup.send(f"✅ {count} offene Raids gecancelt.", ephemeral=True)

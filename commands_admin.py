# commands_admin.py
import discord
from discord import app_commands
from sqlalchemy import select

from db import get_session
from models import Raid
from helpers import delete_raid_completely
from roles import cleanup_temp_role
from raidlist import schedule_raidlist_refresh


def register_admin_commands(tree: app_commands.CommandTree):

    @tree.command(
        name="cancel_all_raids",
        description="❌ Löscht alle offenen Raids auf diesem Server."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_all_raids(interaction: discord.Interaction):

        if not interaction.guild:
            return await interaction.response.send_message(
                "Nur im Server nutzbar.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        deleted_count = 0

        async with await get_session() as session:
            result = await session.execute(
                select(Raid).where(
                    Raid.guild_id == guild_id,
                    Raid.status == "open"
                )
            )
            raids = result.scalars().all()

            for raid in raids:
                try:
                    # Teilnehmerlisten löschen + Rollen entfernen
                    await cleanup_temp_role(session, interaction.guild, raid)

                    # Raid + Votes + Slots etc. löschen
                    await delete_raid_completely(session, raid.id)

                    deleted_count += 1
                except Exception as e:
                    print(f"[ADMIN CANCEL] Fehler bei Raid {raid.id}: {e}")

        # Raidlist sauber aktualisieren (debounced)
        await schedule_raidlist_refresh(interaction.client, guild_id)

        await interaction.followup.send(
            f"✅ {deleted_count} offene Raids wurden vollständig gelöscht.",
            ephemeral=True
        )

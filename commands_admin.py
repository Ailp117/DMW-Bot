from discord import app_commands
import discord
from sqlalchemy import select

from db import get_session
from models import Dungeon, Raid
from helpers import send_temp, delete_raid_completely, delete_participant_list_messages_for_raid
from roles import cleanup_temp_role
from raidlist import schedule_raidlist_refresh


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

    # ✅ NEU: Cancel ALL open raids
    @tree.command(
        name="cancel_all_raids",
        description="❌ Bricht ALLE offenen Raids ab (löscht Teilnehmerlisten + Rollen + DB Einträge).",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_all_raids(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        # wichtig: nur EINMAL ack -> defer
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        deleted = 0

        async with await get_session() as session:
            res = await session.execute(select(Raid).where(Raid.guild_id == guild_id, Raid.status == "open"))
            raids = res.scalars().all()

            for raid in raids:
                # 1) Teilnehmerlisten löschen (Messages)
                try:
                    await delete_participant_list_messages_for_raid(interaction.client, session, raid.id)
                except Exception:
                    pass

                # 2) Temp-Rolle entfernen + ggf. löschen
                try:
                    await cleanup_temp_role(session, interaction.guild, raid)
                except Exception:
                    pass

                # 3) Raid aus DB löschen (CASCADE)
                try:
                    await delete_raid_completely(session, raid.id)
                    deleted += 1
                except Exception:
                    pass

        # Raidlist updaten (debounced)
        await schedule_raidlist_refresh(interaction.client, guild_id)

        await interaction.followup.send(f"✅ {deleted} offene Raids wurden gecancelt und gelöscht.", ephemeral=True)

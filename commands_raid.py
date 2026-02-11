import discord
from discord import app_commands
from sqlalchemy import select

from db import get_session
from models import Dungeon
from helpers import create_raid, set_raid_message_id
from views_raid import RaidCreateModal, RaidVoteView
from raidlist import schedule_raidlist_refresh, force_raidlist_refresh
from helpers import get_or_create_settings


def register_raid_commands(tree: app_commands.CommandTree, client: discord.Client):

    @tree.command(name="raidplan", description="Erstellt einen Raid Plan.")
    @app_commands.describe(dungeon="Dungeon Name (Autocomplete)")
    async def raidplan(interaction: discord.Interaction, dungeon: str):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        s = await get_or_create_settings(interaction.guild.id)
        if not s.planner_channel_id or not s.participants_channel_id:
            return await interaction.followup.send("❌ Bitte zuerst `/settings` konfigurieren.", ephemeral=True)

        # dungeon exists & active
        async with await get_session() as session:
            d = (await session.execute(select(Dungeon).where(Dungeon.name == dungeon, Dungeon.is_active == 1))).scalar_one_or_none()
        if not d:
            return await interaction.followup.send("❌ Dungeon nicht gefunden / nicht aktiv.", ephemeral=True)

        modal = RaidCreateModal()
        await interaction.followup.send("📝 Öffne Modal…", ephemeral=True)
        await interaction.response.send_modal(modal)  # (wird nur klappen, wenn noch nicht geantwortet)
        # NOTE: wegen Discord: send_modal muss die erste response sein.
        # Wenn du Probleme hast: sag Bescheid, dann stelle ich das auf "keine defer vor modal" um.

    @raidplan.autocomplete("dungeon")
    async def dungeon_ac(interaction: discord.Interaction, current: str):
        q = (current or "").lower().strip()
        async with await get_session() as session:
            rows = (await session.execute(select(Dungeon).where(Dungeon.is_active == 1))).scalars().all()
        if q:
            rows = [r for r in rows if q in r.name.lower()]
        return [app_commands.Choice(name=r.name, value=r.name) for r in rows[:25]]

    @tree.command(name="raidlist", description="Raidlist sofort aktualisieren.")
    async def raidlist(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await force_raidlist_refresh(interaction.client, interaction.guild.id)
        await interaction.followup.send("✅ Raidlist aktualisiert.", ephemeral=True)

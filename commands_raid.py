import discord
from discord import app_commands
from sqlalchemy import select

from db import session_scope
from models import Dungeon
from views_raid import RaidCreateModal
from raidlist import force_raidlist_refresh


def register_raid_commands(tree: app_commands.CommandTree):

    @tree.command(name="raidplan", description="Erstellt einen Raid Plan (Modal).")
    @app_commands.describe(dungeon="Dungeon Name (Autocomplete)")
    async def raidplan(interaction: discord.Interaction, dungeon: str):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        # ✅ validate dungeon + settings BEFORE sending modal (modal must be first ack if shown)
        async with session_scope() as session:
            d = (await session.execute(
                select(Dungeon).where(Dungeon.name == dungeon, Dungeon.is_active.is_(True))
            )).scalar_one_or_none()

            if not d:
                return await interaction.response.send_message("❌ Dungeon nicht gefunden / nicht aktiv.", ephemeral=True)

            # settings check
            from helpers import get_settings
            s = await get_settings(session, interaction.guild.id)
            if not s.planner_channel_id or not s.participants_channel_id:
                return await interaction.response.send_message(
                    "❌ Bitte zuerst `/settings` konfigurieren (Planner + Participants Channel).",
                    ephemeral=True
                )

        # ✅ modal MUST be the first response for this interaction
        await interaction.response.send_modal(RaidCreateModal(dungeon_name=dungeon))

    @raidplan.autocomplete("dungeon")
    async def dungeon_ac(interaction: discord.Interaction, current: str):
        q = (current or "").lower().strip()

        async with session_scope() as session:
            rows = (await session.execute(
                select(Dungeon)
                .where(Dungeon.is_active.is_(True))
                .order_by(Dungeon.sort_order.asc(), Dungeon.name.asc())
            )).scalars().all()

        if q:
            rows = [r for r in rows if q in (r.name or "").lower()]

        return [app_commands.Choice(name=r.name, value=r.name) for r in rows[:25]]

    @tree.command(name="raidlist", description="Raidlist sofort aktualisieren.")
    async def raidlist(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await force_raidlist_refresh(interaction.client, interaction.guild.id)
        await interaction.followup.send("✅ Raidlist aktualisiert.", ephemeral=True)

import discord
from discord import app_commands
from sqlalchemy import select

from db import session_scope
from helpers import (
    AUTO_DUNGEON_TEMPLATE_NAME,
    get_active_dungeons,
    get_settings,
    get_template_by_name,
    load_template_data,
)
from models import Dungeon
from views_raid import RaidCreateModal
from raidlist import force_raidlist_refresh


def register_raid_commands(tree: app_commands.CommandTree):

    @tree.command(name="raidplan", description="Erstellt einen Raid Plan (Modal).")
    @app_commands.describe(dungeon="Dungeon Name (Autocomplete)")
    async def raidplan(interaction: discord.Interaction, dungeon: str):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        # validate dungeon + settings before modal response
        async with session_scope() as session:
            d = (await session.execute(
                select(Dungeon).where(Dungeon.name == dungeon, Dungeon.is_active.is_(True))
            )).scalar_one_or_none()

            if not d:
                return await interaction.response.send_message("❌ Dungeon nicht gefunden / nicht aktiv.", ephemeral=True)

            s = await get_settings(session, interaction.guild.id, interaction.guild.name)
            if not s.planner_channel_id or not s.participants_channel_id:
                return await interaction.response.send_message(
                    "❌ Bitte zuerst `/settings` konfigurieren (Planner + Participants Channel).",
                    ephemeral=True,
                )

            template_defaults: tuple[list[str], list[str], int] | None = None
            if s.templates_enabled:
                auto_tpl = await get_template_by_name(session, interaction.guild.id, d.id, AUTO_DUNGEON_TEMPLATE_NAME)
                if auto_tpl is not None:
                    template_defaults = load_template_data(auto_tpl.template_data)

            if template_defaults is None:
                template_defaults = ([], [], max(0, int(s.default_min_players or 0)))

        await interaction.response.send_modal(
            RaidCreateModal(
                dungeon_name=dungeon,
                default_days=template_defaults[0],
                default_times=template_defaults[1],
                default_min_players=template_defaults[2],
            )
        )

    @raidplan.autocomplete("dungeon")
    async def dungeon_ac(interaction: discord.Interaction, current: str):
        q = (current or "").lower().strip()

        async with session_scope() as session:
            rows = await get_active_dungeons(session)

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

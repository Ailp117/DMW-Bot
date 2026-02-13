import discord
from discord import app_commands

from db import session_scope
from helpers import get_settings


def register_template_commands(tree: app_commands.CommandTree):
    @tree.command(name="template_config", description="Aktiviert/deaktiviert Auto-Templates pro Server.")
    @app_commands.describe(enabled="Auto-Templates aktiv")
    async def template_config(interaction: discord.Interaction, enabled: bool):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and getattr(perms, "administrator", False)):
            return await interaction.response.send_message("❌ Nur für Admins.", ephemeral=True)

        async with session_scope() as session:
            settings = await get_settings(session, interaction.guild.id, interaction.guild.name)
            settings.templates_enabled = enabled

        await interaction.response.send_message(
            f"✅ Auto-Template-Konfiguration gespeichert (aktiv={enabled}).",
            ephemeral=True,
        )

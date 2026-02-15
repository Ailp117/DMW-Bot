"""Language selection component for settings."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bot.discord_api import discord
from utils.localization import Language, get_string

if TYPE_CHECKING:
    from views.raid_views import SettingsView


class SettingsLanguageSelect(discord.ui.Select):
    """Select component für Sprach-Auswahl."""
    
    def __init__(self, bot: Any, *, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        
        options = [
            discord.SelectOption(
                label="🇩🇪 Deutsch",
                value="de",
                description="Deutsche Sprache",
                emoji="🇩🇪"
            ),
            discord.SelectOption(
                label="🇬🇧 English",
                value="en",
                description="English language",
                emoji="🇬🇧"
            )
        ]
        
        super().__init__(
            placeholder="🌍 Sprache / Language wählen...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id=f"settings:{guild_id}:language",
            row=2
        )
    
    async def callback(self, interaction: "discord.Interaction") -> None:  # type: ignore[name-defined]
        view = self.view
        if not hasattr(view, "build_embed"):
            return
        
        selected_lang = self.values[0] if self.values else "de"
        view.language = selected_lang  # type: ignore
        
        # Update Embed
        await interaction.response.edit_message(
            embed=view.build_embed(),  # type: ignore
            view=view
        )
        
        lang_name = "🇩🇪 Deutsch" if selected_lang == "de" else "🇬🇧 English"
        msg = f"🌍 Sprache geändert zu: **{lang_name}**" if selected_lang == "de" else f"🌍 Language changed to: **{lang_name}**"
        await interaction.followup.send(msg, ephemeral=True)


__all__ = ["SettingsLanguageSelect"]

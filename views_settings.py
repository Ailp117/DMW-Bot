# views_settings.py
import discord
from discord.ui import View
from db import get_session
from models import GuildSettings
from raidlist import force_raidlist_refresh
from helpers import get_guild_settings


def settings_embed(settings: GuildSettings | None, guild: discord.Guild) -> discord.Embed:
    def ch_mention(cid: int | None) -> str:
        if not cid:
            return "—"
        ch = guild.get_channel(cid)
        return ch.mention if ch else f"`{cid}` (nicht gefunden)"

    e = discord.Embed(title="⚙️ Settings", description="Hier kannst du alle Raid-Bot Einstellungen setzen.")
    if settings:
        e.add_field(name="Teilnehmerlisten-Channel", value=ch_mention(settings.participants_channel_id), inline=False)
        e.add_field(name="Planer-Channel", value=ch_mention(settings.planner_channel_id), inline=False)
        e.add_field(name="Raidlist-Channel", value=ch_mention(settings.raidlist_channel_id), inline=False)
    else:
        e.add_field(name="Status", value="Noch keine Settings vorhanden.", inline=False)
    e.set_footer(text="Speichern nicht vergessen.")
    return e


class SettingsView(View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

        self.participants_select = discord.ui.ChannelSelect(
            placeholder="Teilnehmerlisten-Channel wählen… (Pflicht)",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=1,
        )
        self.planner_select = discord.ui.ChannelSelect(
            placeholder="Planer-Channel wählen… (Pflicht)",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=1,
        )
        self.raidlist_select = discord.ui.ChannelSelect(
            placeholder="Raidlist-Channel wählen… (Optional)",
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=1,
        )

        self.participants_select.callback = self._preview
        self.planner_select.callback = self._preview
        self.raidlist_select.callback = self._preview

        self.add_item(self.participants_select)
        self.add_item(self.planner_select)
        self.add_item(self.raidlist_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Du brauchst `Manage Server` für Settings.", ephemeral=True)
            return False
        return True

    async def _preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with await get_session() as session:
            row = await get_guild_settings(session, self.guild_id)
        await interaction.edit_original_response(embed=settings_embed(row, interaction.guild), view=self)

    @discord.ui.button(label="💾 Speichern", style=discord.ButtonStyle.success)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        participants = self.participants_select.values[0].id if self.participants_select.values else None
        planner = self.planner_select.values[0].id if self.planner_select.values else None
        raidlist = self.raidlist_select.values[0].id if self.raidlist_select.values else None

        async with await get_session() as session:
            row = await session.get(GuildSettings, self.guild_id)

            if row is None:
                if not participants or not planner:
                    return await interaction.followup.send(
                        "❌ Bitte **Teilnehmerlisten-Channel** und **Planer-Channel** auswählen (beide Pflicht).",
                        ephemeral=True,
                    )
                row = GuildSettings(
                    guild_id=self.guild_id,
                    participants_channel_id=participants,
                    planner_channel_id=planner,
                    raidlist_channel_id=raidlist,
                )
                session.add(row)
                await session.commit()
            else:
                if participants:
                    row.participants_channel_id = participants
                if planner:
                    row.planner_channel_id = planner
                if raidlist is not None:
                    if row.raidlist_channel_id != raidlist:
                        row.raidlist_channel_id = raidlist
                        row.raidlist_message_id = None
                await session.commit()

            row2 = await session.get(GuildSettings, self.guild_id)

        await interaction.edit_original_response(embed=settings_embed(row2, interaction.guild), view=self)
        await interaction.followup.send("✅ Gespeichert.", ephemeral=True)

        # ✅ immediate refresh after settings save
        await force_raidlist_refresh(interaction.client, self.guild_id)

    @discord.ui.button(label="❌ Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.edit_original_response(content="Abgebrochen.", embed=None, view=self)

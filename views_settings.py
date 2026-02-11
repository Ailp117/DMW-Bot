import discord
from discord.ui import View
from helpers import get_or_create_settings, set_settings
from raidlist import force_raidlist_refresh


def settings_embed(s, guild: discord.Guild) -> discord.Embed:
    def m(cid):
        if not cid:
            return "—"
        ch = guild.get_channel(int(cid))
        return ch.mention if ch else f"`{cid}`"

    e = discord.Embed(title="⚙️ Settings", description="Planner / Participants / Raidlist Channels setzen.")
    e.add_field(name="Planner Channel", value=m(s.planner_channel_id), inline=False)
    e.add_field(name="Participants Channel", value=m(s.participants_channel_id), inline=False)
    e.add_field(name="Raidlist Channel", value=m(s.raidlist_channel_id), inline=False)
    return e


class SettingsView(View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

        self.sel_planner = discord.ui.ChannelSelect(
            placeholder="Planner Channel (Pflicht)",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1
        )
        self.sel_participants = discord.ui.ChannelSelect(
            placeholder="Participants Channel (Pflicht)",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1
        )
        self.sel_raidlist = discord.ui.ChannelSelect(
            placeholder="Raidlist Channel (Optional)",
            channel_types=[discord.ChannelType.text],
            min_values=0, max_values=1
        )

        self.add_item(self.sel_planner)
        self.add_item(self.sel_participants)
        self.add_item(self.sel_raidlist)

    @discord.ui.button(label="💾 Speichern", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        planner = self.sel_planner.values[0].id if self.sel_planner.values else None
        participants = self.sel_participants.values[0].id if self.sel_participants.values else None
        raidlist = self.sel_raidlist.values[0].id if self.sel_raidlist.values else None

        await set_settings(self.guild_id, planner, participants, raidlist)
        s = await get_or_create_settings(self.guild_id)

        await interaction.edit_original_response(embed=settings_embed(s, interaction.guild), view=self)
        await interaction.followup.send("✅ Gespeichert.", ephemeral=True)

        if raidlist:
            await force_raidlist_refresh(interaction.client, self.guild_id)

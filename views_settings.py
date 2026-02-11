import discord
from discord.ui import View
from db import session_scope
from helpers import get_settings
from raidlist import force_raidlist_refresh

def settings_embed(s, guild: discord.Guild) -> discord.Embed:
    def fmt(cid):
        if not cid:
            return "—"
        ch = guild.get_channel(int(cid))
        return ch.mention if ch else f"`{cid}`"

    e = discord.Embed(title="⚙️ Settings")
    e.add_field(name="Planner Channel", value=fmt(s.planner_channel_id), inline=False)
    e.add_field(name="Participants Channel", value=fmt(s.participants_channel_id), inline=False)
    e.add_field(name="Raidlist Channel", value=fmt(s.raidlist_channel_id), inline=False)
    return e

class SettingsView(View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

        self.sel_planner = discord.ui.ChannelSelect(
            placeholder="Planner Channel (Pflicht)",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1,
        )
        self.sel_participants = discord.ui.ChannelSelect(
            placeholder="Participants Channel (Pflicht)",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1,
        )
        self.sel_raidlist = discord.ui.ChannelSelect(
            placeholder="Raidlist Channel (Optional)",
            channel_types=[discord.ChannelType.text],
            min_values=0, max_values=1,
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

        async with session_scope() as session:
            s = await get_settings(session, self.guild_id)
            s.planner_channel_id = planner
            s.participants_channel_id = participants
            if raidlist is not None:
                if s.raidlist_channel_id != raidlist:
                    s.raidlist_channel_id = raidlist
                    s.raidlist_message_id = None

        async with session_scope() as session:
            s2 = await get_settings(session, self.guild_id)

        await interaction.edit_original_response(embed=settings_embed(s2, interaction.guild), view=self)
        await interaction.followup.send("✅ Gespeichert.", ephemeral=True)

        if raidlist:
            await force_raidlist_refresh(interaction.client, self.guild_id)

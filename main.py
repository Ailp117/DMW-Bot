import logging
import discord
from discord import app_commands

from config import DISCORD_TOKEN
from db import ensure_schema, get_session
from helpers import get_options
from models import Raid
from raidlist import refresh_raidlists_for_all_guilds
from views_raid import RaidVoteView
from commands_admin import register_admin_commands
from commands_raid import register_raid_commands
from commands_purge import register_purge_commands
from views_settings import SettingsView, settings_embed
from helpers import get_guild_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dmw-raid-bot")

INTENTS = discord.Intents.default()

class RaidBot(discord.Client):
    def __init__(self):
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await ensure_schema()

        register_admin_commands(self.tree)
        register_raid_commands(self.tree, self)
        register_purge_commands(self.tree)

        @self.tree.command(name="settings", description="Öffnet das Settings-Menü (alle Einstellungen in einem Popup).")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def settings_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)
            async with await get_session() as session:
                row = await get_guild_settings(session, interaction.guild.id)
            view = SettingsView(interaction.guild.id)
            await interaction.response.send_message(embed=settings_embed(row, interaction.guild), view=view, ephemeral=True)

        await self.tree.sync()
        await self._restore_open_raid_views()
        await refresh_raidlists_for_all_guilds(self)

    async def _restore_open_raid_views(self):
        from sqlalchemy import select
        async with await get_session() as session:
            res = await session.execute(select(Raid).where(Raid.status == "open", Raid.message_id.is_not(None)))
            raids = res.scalars().all()
            for raid in raids:
                try:
                    days, times = await get_options(session, raid.id)
                    if not days or not times:
                        continue
                    view = RaidVoteView(raid.id, days, times)
                    self.add_view(view, message_id=raid.message_id)
                except Exception as e:
                    log.warning("Restore view failed for raid_id=%s: %s", raid.id, e)

client = RaidBot()

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

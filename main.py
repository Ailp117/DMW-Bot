import logging
import discord
from discord import app_commands

from config import DISCORD_TOKEN, GUILD_ID
from ensure_schema import ensure_schema
from db import try_acquire_singleton_lock, session_scope
from raidlist_updater import RaidlistUpdater
from raidlist import refresh_raidlist_for_guild, force_raidlist_refresh
from views_settings import SettingsView, settings_embed
from helpers import get_settings

from commands_admin import register_admin_commands
from commands_raid import register_raid_commands
from commands_purge import register_purge_commands

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dmw-raid-bot")

INTENTS = discord.Intents.default()

class RaidBot(discord.Client):
    def __init__(self):
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)
        self.raidlist_updater: RaidlistUpdater | None = None

    async def setup_hook(self):
        await ensure_schema()

        if not await try_acquire_singleton_lock():
            log.warning("Another instance is running (singleton lock busy). Exiting.")
            raise SystemExit(0)

        async def _update(gid: int):
            await refresh_raidlist_for_guild(self, gid)

        self.raidlist_updater = RaidlistUpdater(_update, debounce_seconds=1.5, cooldown_seconds=0.8)

        register_admin_commands(self.tree)
        register_raid_commands(self.tree)
        register_purge_commands(self.tree)

        @self.tree.command(name="settings", description="Settings öffnen")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def settings_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server.", ephemeral=True)

            async with session_scope() as session:
                s = await get_settings(session, interaction.guild.id)

            view = SettingsView(interaction.guild.id)
            await interaction.response.send_message(embed=settings_embed(s, interaction.guild), view=view, ephemeral=True)

        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.warning("GUILD_ID not set -> global sync (can take up to ~1h).")

    async def on_ready(self):
        log.info("Logged in as %s", self.user)
        if self.guilds:
            await force_raidlist_refresh(self, self.guilds[0].id)

client = RaidBot()

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

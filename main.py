import logging
import discord
from discord import app_commands

from config import DISCORD_TOKEN, GUILD_ID
from db import ensure_schema, get_session, try_acquire_singleton_lock
from helpers import get_options, get_guild_settings
from models import Raid
from raidlist import refresh_raidlists_for_all_guilds, refresh_raidlist_for_guild
from raidlist_updater import RaidlistUpdater
from views_raid import RaidVoteView
from commands_admin import register_admin_commands
from commands_raid import register_raid_commands
from commands_purge import register_purge_commands
from views_settings import SettingsView, settings_embed

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

        # Prevent multiple instances from running (important with GitHub Actions restarts)
        got_lock = await try_acquire_singleton_lock()
        if not got_lock:
            log.warning("Another bot instance is already running (singleton lock busy). Exiting.")
            raise SystemExit(0)

        # Debounced raidlist updater (coalesces many changes into one edit)
        async def _update(guild_id: int):
            await refresh_raidlist_for_guild(self, guild_id)

        self.raidlist_updater = RaidlistUpdater(
            update_fn=_update,
            debounce_seconds=1.5,
            cooldown_seconds=0.8,
        )

        register_admin_commands(self.tree)
        register_raid_commands(self.tree, self)
        register_purge_commands(self.tree)

        @self.tree.command(
            name="settings",
            description="Öffnet das Settings-Menü (alle Einstellungen in einem Popup).",
        )
        @app_commands.checks.has_permissions(manage_guild=True)
        async def settings_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

            async with await get_session() as session:
                row = await get_guild_settings(session, interaction.guild.id)

            view = SettingsView(interaction.guild.id)
            await interaction.response.send_message(
                embed=settings_embed(row, interaction.guild),
                view=view,
                ephemeral=True,
            )

        # ✅ Instant slash-command availability for private single-guild bots
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            # Global sync (may take a while to appear)
            await self.tree.sync()
            log.warning("GUILD_ID not set -> global sync (can take up to ~1 hour to show new commands).")

        await self._restore_open_raid_views()
        await refresh_raidlists_for_all_guilds(self)

    async def _restore_open_raid_views(self):
        from sqlalchemy import select

        async with await get_session() as session:
            res = await session.execute(
                select(Raid).where(Raid.status == "open", Raid.message_id.is_not(None))
            )
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

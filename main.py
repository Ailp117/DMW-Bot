import asyncio
import logging
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from sqlalchemy import select

from config import DISCORD_TOKEN, GUILD_ID, ENABLE_MESSAGE_CONTENT_INTENT
from ensure_schema import ensure_schema
from db import try_acquire_singleton_lock, session_scope
from raidlist_updater import RaidlistUpdater
from raidlist import refresh_raidlist_for_guild, force_raidlist_refresh, schedule_raidlist_refresh
from views_settings import SettingsView, settings_embed
from helpers import get_settings, delete_raid_cascade

from commands_admin import register_admin_commands
from commands_raid import register_raid_commands
from commands_purge import register_purge_commands
from models import Raid
from roles import cleanup_temp_role
from views_raid import cleanup_posted_slot_messages

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dmw-raid-bot")

NANOMON_IMAGE_URL = "https://wikimon.net/images/thumb/c/cc/Nanomon_New_Century.png/200px-Nanomon_New_Century.png"
NANOMON_PATTERN = re.compile(r"\bnanomon\b")
STALE_RAID_HOURS = 7 * 24
STALE_RAID_CHECK_SECONDS = 15 * 60


def contains_nanomon_keyword(content: str) -> bool:
    return bool(NANOMON_PATTERN.search((content or "").casefold()))




def _channel_status(guild: discord.Guild, channel_id: int | None) -> str:
    if not channel_id:
        return "❌ nicht gesetzt"
    ch = guild.get_channel(int(channel_id))
    if ch is None:
        return f"⚠️ `{channel_id}` (nicht gefunden)"
    return f"✅ {ch.mention}"


def _perm_status(channel: discord.TextChannel | None, me: discord.Member | None) -> str:
    if channel is None:
        return "—"
    if me is None:
        return "⚠️ Bot-Mitglied unbekannt"
    p = channel.permissions_for(me)
    return (
        f"read={ '✅' if p.read_messages else '❌' }, "
        f"history={ '✅' if p.read_message_history else '❌' }, "
        f"send={ '✅' if p.send_messages else '❌' }, "
        f"manage={ '✅' if p.manage_messages else '❌' }"
    )

INTENTS = discord.Intents.default()
INTENTS.message_content = True

class RaidBot(discord.Client):
    def __init__(self):
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)
        self.raidlist_updater: RaidlistUpdater | None = None
        self.stale_raid_task: asyncio.Task | None = None

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

        await self.restore_persistent_raid_views()

        @self.tree.command(name="settings", description="Settings öffnen")
        @app_commands.checks.has_permissions(manage_guild=True)
        async def settings_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server.", ephemeral=True)

            async with session_scope() as session:
                s = await get_settings(session, interaction.guild.id)

            view = SettingsView(interaction.guild.id)
            await interaction.response.send_message(embed=settings_embed(s, interaction.guild), view=view, ephemeral=True)




        @self.tree.command(name="status", description="Zeigt Bot-Status, Settings und Berechtigungen")
        async def status_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server.", ephemeral=True)

            async with session_scope() as session:
                settings = await get_settings(session, interaction.guild.id)

            me = interaction.guild.me or interaction.guild.get_member(self.user.id if self.user else 0)
            planner_ch = interaction.guild.get_channel(int(settings.planner_channel_id)) if settings.planner_channel_id else None
            participants_ch = interaction.guild.get_channel(int(settings.participants_channel_id)) if settings.participants_channel_id else None
            raidlist_ch = interaction.guild.get_channel(int(settings.raidlist_channel_id)) if settings.raidlist_channel_id else None

            e = discord.Embed(title="📊 DMW Bot Status", description=f"Server: **{interaction.guild.name}**")
            e.add_field(name="Planner Channel", value=_channel_status(interaction.guild, settings.planner_channel_id), inline=False)
            e.add_field(name="Participants Channel", value=_channel_status(interaction.guild, settings.participants_channel_id), inline=False)
            e.add_field(name="Raidlist Channel", value=_channel_status(interaction.guild, settings.raidlist_channel_id), inline=False)

            e.add_field(name="Planner Rechte", value=_perm_status(planner_ch, me), inline=False)
            e.add_field(name="Participants Rechte", value=_perm_status(participants_ch, me), inline=False)
            e.add_field(name="Raidlist Rechte", value=_perm_status(raidlist_ch, me), inline=False)

            stale_running = bool(self.stale_raid_task and not self.stale_raid_task.done())
            e.add_field(
                name="Background Jobs",
                value=(
                    f"Stale Cleanup: {'✅ aktiv' if stale_running else '❌ inaktiv'}\n"
                    f"Cutoff: {STALE_RAID_HOURS}h | Intervall: {STALE_RAID_CHECK_SECONDS}s"
                ),
                inline=False,
            )
            e.add_field(name="Intents", value=f"message_content={'✅' if INTENTS.message_content else '❌'}", inline=False)

            await interaction.response.send_message(embed=e, ephemeral=True)

        @self.tree.command(name="help", description="Zeigt verfügbare Commands und Kurzinfos")
        async def help_cmd(interaction: discord.Interaction):
            text = (
                "**DMW Raid Bot Hilfe**\n"
                "`/raidplan` - Raid erstellen\n"
                "`/raidlist` - Raidlist sofort aktualisieren\n"
                "`/settings` - Bot-Channels konfigurieren\n"
                "`/dungeonlist` - aktive Dungeons anzeigen\n"
                "`/cancel_all_raids` - alle offenen Raids stoppen (Admin)\n"
                "`/purge` - letzte N Nachrichten löschen\n"
                "`/purgebot` - Bot-Nachrichten channelweit/serverweit löschen\n"
                "\n"
                f"Stale-Raid Auto-Cleanup: offen > {STALE_RAID_HOURS}h wird automatisch beendet."
            )
            await interaction.response.send_message(text, ephemeral=True)

        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.warning("GUILD_ID not set -> global sync (can take up to ~1h).")

        if self.stale_raid_task is None or self.stale_raid_task.done():
            self.stale_raid_task = asyncio.create_task(self._stale_raid_worker())



    async def cleanup_stale_raids_once(self) -> int:
        cutoff = datetime.utcnow() - timedelta(hours=STALE_RAID_HOURS)
        total_cleaned = 0

        for guild in self.guilds:
            async with session_scope() as session:
                stale_raids = (await session.execute(
                    select(Raid).where(
                        Raid.guild_id == guild.id,
                        Raid.status == "open",
                        Raid.created_at <= cutoff,
                    )
                )).scalars().all()

                for raid in stale_raids:
                    await cleanup_posted_slot_messages(session, self, raid.id)
                    await cleanup_temp_role(session, guild, raid)
                    await delete_raid_cascade(session, raid.id)
                    total_cleaned += 1

            if stale_raids:
                await schedule_raidlist_refresh(self, guild.id)

        if total_cleaned:
            log.info("Stale raid cleanup removed %s raids", total_cleaned)

        return total_cleaned

    async def _stale_raid_worker(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.cleanup_stale_raids_once()
            except Exception:
                log.exception("Stale raid cleanup failed")
            await asyncio.sleep(STALE_RAID_CHECK_SECONDS)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if contains_nanomon_keyword(message.content):
            await message.reply(NANOMON_IMAGE_URL, mention_author=False)

    async def on_ready(self):
        log.info("Logged in as %s", self.user)
        if self.guilds:
            await force_raidlist_refresh(self, self.guilds[0].id)

    async def close(self):
        if self.stale_raid_task and not self.stale_raid_task.done():
            self.stale_raid_task.cancel()
        await super().close()

client = RaidBot()

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

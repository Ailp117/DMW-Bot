import asyncio
import logging
import os
import re
import shlex
import sys
from collections import deque
from datetime import datetime, timedelta

import discord
from discord import app_commands
from sqlalchemy import select, func

from config import (
    DISCORD_TOKEN,
    ENABLE_MESSAGE_CONTENT_INTENT,
    LOG_GUILD_ID,
    LOG_CHANNEL_ID,
    SELF_TEST_INTERVAL_SECONDS,
    DISCORD_LOG_LEVEL,
    BACKUP_INTERVAL_SECONDS,
)
from ensure_schema import ensure_schema
from db import try_acquire_singleton_lock, session_scope
from raidlist_updater import RaidlistUpdater
from raidlist import refresh_raidlist_for_guild, force_raidlist_refresh, schedule_raidlist_refresh
from views_settings import SettingsView, settings_embed
from helpers import get_settings, delete_raid_cascade, get_options, purge_guild_data

from commands_admin import register_admin_commands
from commands_raid import register_raid_commands
from commands_purge import register_purge_commands
from commands_remote import register_remote_commands
from commands_templates import register_template_commands
from commands_attendance import register_attendance_commands
from commands_backup import register_backup_commands
from backup_sql import export_database_to_sql
from models import Raid, UserLevel, GuildSettings, Dungeon
from roles import cleanup_temp_role
from views_raid import RaidVoteView, cleanup_posted_slot_messages, sync_memberlists_for_raid
from leveling import calculate_level_from_xp
from permissions import admin_or_privileged_check

def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    log_level = getattr(logging, level_name, logging.DEBUG)

    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)s [%(name)s|%(module)s.%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


setup_logging()
log = logging.getLogger("dmw-raid-bot")

NANOMON_IMAGE_URL = "https://wikimon.net/images/thumb/c/cc/Nanomon_New_Century.png/200px-Nanomon_New_Century.png"
NANOMON_PATTERN = re.compile(r"\bnanomon\b")
APPROVED_GIF_URL = "https://media1.tenor.com/m/l8waltLHrxcAAAAC/approved.gif"
APPROVED_PATTERN = re.compile(r"\bapproved\b")
STALE_RAID_HOURS = 7 * 24
STALE_RAID_CHECK_SECONDS = 15 * 60
VOICE_XP_CHECK_SECONDS = 60
VOICE_XP_AWARD_INTERVAL = timedelta(hours=1)

EXPECTED_SLASH_COMMANDS = {
    "settings", "status", "help", "help2", "restart",
    "raidplan", "raidlist", "dungeonlist", "cancel_all_raids", "purge", "purgebot",
    "remote_guilds", "remote_cancel_all_raids", "remote_raidlist",
    "template_config",
    "attendance_list", "attendance_mark", "backup_db",
}


def contains_nanomon_keyword(content: str) -> bool:
    return bool(NANOMON_PATTERN.search((content or "").casefold()))


def contains_approved_keyword(content: str) -> bool:
    return bool(APPROVED_PATTERN.search((content or "").casefold()))


def _member_username_in_guild(member: discord.abc.User) -> str | None:
    display_name = getattr(member, "display_name", None)
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()

    global_name = getattr(member, "global_name", None)
    if isinstance(global_name, str) and global_name.strip():
        return global_name.strip()

    username = getattr(member, "name", None)
    if isinstance(username, str) and username.strip():
        return username.strip()

    return None


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




def _is_server_admin(interaction: discord.Interaction) -> bool:
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and getattr(perms, "administrator", False))
INTENTS = discord.Intents.default()
INTENTS.message_content = ENABLE_MESSAGE_CONTENT_INTENT

class RaidBot(discord.Client):
    def __init__(self):
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)
        self.raidlist_updater: RaidlistUpdater | None = None
        self.stale_raid_task: asyncio.Task | None = None
        self.voice_xp_task: asyncio.Task | None = None
        self.self_test_task: asyncio.Task | None = None
        self.backup_task: asyncio.Task | None = None
        self.voice_xp_last_award: dict[tuple[int, int], datetime] = {}
        self.last_self_test_ok_at: datetime | None = None
        self.last_self_test_error: str | None = None
        self.log_channel: discord.TextChannel | None = None
        self.log_forwarder_task: asyncio.Task | None = None
        self.log_forward_queue: asyncio.Queue[str] = asyncio.Queue()
        self.pending_log_buffer: deque[str] = deque(maxlen=250)
        self._startup_guild_cleanup_done = False
        self._ready_sync_done = False
        self._initial_raidlist_refresh_done = False
        self._initial_memberlist_restore_done = False
        self._discord_log_handler = self._build_discord_log_handler()
        log.addHandler(self._discord_log_handler)

    async def _get_configured_guild_ids(self) -> list[int]:
        async with session_scope() as session:
            guild_ids = (await session.execute(select(GuildSettings.guild_id))).scalars().all()
        return sorted({int(gid) for gid in guild_ids if gid})

    async def _get_known_guild_ids_from_db(self) -> list[int]:
        async with session_scope() as session:
            settings_ids = (await session.execute(select(GuildSettings.guild_id))).scalars().all()
            raid_ids = (await session.execute(select(Raid.guild_id))).scalars().all()
            level_ids = (await session.execute(select(UserLevel.guild_id))).scalars().all()

        return sorted({int(gid) for gid in [*settings_ids, *raid_ids, *level_ids] if gid})

    async def _cleanup_removed_guild_data_on_startup(self) -> None:
        db_guild_ids = set(await self._get_known_guild_ids_from_db())
        connected_guild_ids = {guild.id for guild in self.guilds}
        removed_guild_ids = sorted(db_guild_ids - connected_guild_ids)

        if not removed_guild_ids:
            return

        cleaned = 0
        for guild_id in removed_guild_ids:
            try:
                async with session_scope() as session:
                    deleted = await purge_guild_data(session, guild_id)
                self.voice_xp_last_award = {
                    key: value for key, value in self.voice_xp_last_award.items() if key[0] != guild_id
                }
                cleaned += 1
                log.info(
                    "Startup cleanup removed stale guild %s data (raids=%s, user_levels=%s, guild_settings=%s)",
                    guild_id,
                    deleted["raids"],
                    deleted["user_levels"],
                    deleted["guild_settings"],
                )
            except Exception:
                log.exception("Startup cleanup failed for removed guild %s", guild_id)

        log.info("Startup guild cleanup processed %s removed guild(s).", cleaned)

    def _command_registry_health(self) -> tuple[list[str], list[str], list[str]]:
        registered = sorted(cmd.name for cmd in self.tree.get_commands())
        registered_set = set(registered)
        missing = sorted(EXPECTED_SLASH_COMMANDS - registered_set)
        unexpected = sorted(registered_set - EXPECTED_SLASH_COMMANDS)
        return registered, missing, unexpected

    def _log_command_registry_health(self) -> None:
        registered, missing, unexpected = self._command_registry_health()
        if missing or unexpected:
            log.error(
                "Command registry mismatch (registered=%s missing=%s unexpected=%s)",
                ", ".join(registered) or "-",
                ", ".join(missing) or "-",
                ", ".join(unexpected) or "-",
            )
            return

        log.info(
            "Slash commands registered correctly (%s): %s",
            len(registered),
            ", ".join(registered),
        )

    async def _sync_commands_for_known_guilds(self) -> None:
        guild_ids = await self._get_configured_guild_ids()
        connected_guild_ids = {guild.id for guild in self.guilds}
        target_ids = sorted(set(guild_ids).union(connected_guild_ids))

        if not target_ids:
            await self.tree.sync()
            log.warning("No known guild IDs in database yet -> global sync (can take up to ~1h).")
            return

        synced_ids: list[int] = []
        failed_ids: list[int] = []
        for guild_id in target_ids:
            try:
                await self.tree.sync(guild=discord.Object(id=guild_id))
                synced_ids.append(guild_id)
            except discord.Forbidden:
                failed_ids.append(guild_id)
                log.warning(
                    "Skipping command sync for guild %s due to missing access (bot not in guild or insufficient permissions).",
                    guild_id,
                )
            except Exception:
                failed_ids.append(guild_id)
                log.exception("Failed to sync commands to guild %s", guild_id)

        if synced_ids:
            log.info(
                "Synced commands to %s guild(s): %s",
                len(synced_ids),
                ", ".join(str(gid) for gid in synced_ids),
            )
        else:
            log.warning("No guild command syncs succeeded.")

        if failed_ids:
            log.warning(
                "Command sync failed for %s guild(s): %s",
                len(failed_ids),
                ", ".join(str(gid) for gid in failed_ids),
            )

        try:
            await self.tree.sync()
            log.info(
                "Global command sync completed as fallback (Discord propagation can still take up to ~1h)."
            )
        except Exception:
            log.exception("Global command sync failed")

    async def _restart_process(self) -> None:
        log.warning("Restart requested. Restarting bot process now.")
        await self.close()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    async def _execute_console_command(self, message: discord.Message) -> bool:
        raw = (message.content or "").strip()
        if not raw:
            return False

        parts = shlex.split(raw)
        if not parts:
            return False

        command = parts[0].lstrip("/").lower()
        if command == "restart":
            await message.channel.send("♻️ Neustart wird ausgeführt …")
            asyncio.create_task(self._restart_process())
            return True

        await message.channel.send(f"⚠️ Unbekannter Console-Befehl: `{command}`")
        return False

    def _build_discord_log_handler(self) -> logging.Handler:
        bot = self

        class _DiscordQueueHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = self.format(record)
                    bot.enqueue_discord_log(msg)
                except Exception:
                    self.handleError(record)

        discord_level = getattr(logging, DISCORD_LOG_LEVEL, logging.DEBUG)
        handler = _DiscordQueueHandler(level=discord_level)
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s [%(name)s|%(module)s.%(funcName)s] %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        return handler

    def enqueue_discord_log(self, message: str) -> None:
        if not message:
            return

        if len(message) > 1800:
            message = f"{message[:1797]}..."

        if self.is_ready() and self.log_forwarder_task and not self.log_forwarder_task.done():
            self.loop.call_soon_threadsafe(self.log_forward_queue.put_nowait, message)
            return

        self.pending_log_buffer.append(message)

    async def _resolve_log_channel(self) -> discord.TextChannel | None:
        guild = self.get_guild(LOG_GUILD_ID)
        if guild is None:
            log.warning("Log guild %s not found", LOG_GUILD_ID)
            return None

        channel = guild.get_channel(LOG_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            log.warning("Log channel %s not found or not a text channel", LOG_CHANNEL_ID)
            return None

        perms = channel.permissions_for(guild.me) if guild.me else None
        if perms and not perms.send_messages:
            log.warning("Missing send_messages permission in log channel %s", LOG_CHANNEL_ID)
            return None

        return channel

    async def _log_forwarder_worker(self):
        await self.wait_until_ready()

        while not self.is_closed():
            message = await self.log_forward_queue.get()
            channel = self.log_channel
            if channel is None:
                continue

            try:
                await channel.send(f"```\n{message}\n```")
            except Exception:
                # Keep stderr logging only here to avoid recursive handler loops.
                print(f"[discord-log-forwarder] failed to send log message: {message}")

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
        register_remote_commands(self.tree)
        register_template_commands(self.tree)
        register_attendance_commands(self.tree)
        register_backup_commands(self.tree)
        self._log_command_registry_health()

        await self.restore_persistent_raid_views()

        @self.tree.command(name="settings", description="Settings öffnen")
        @admin_or_privileged_check()
        async def settings_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server.", ephemeral=True)

            async with session_scope() as session:
                s = await get_settings(session, interaction.guild.id, interaction.guild.name)

            view = SettingsView(interaction.guild.id)
            await interaction.response.send_message(embed=settings_embed(s, interaction.guild), view=view, ephemeral=True)




        @self.tree.command(name="status", description="Zeigt Kern-Konfiguration für Server-Admins")
        @app_commands.default_permissions(administrator=True)
        async def status_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Nur im Server.", ephemeral=True)
            if not _is_server_admin(interaction):
                return await interaction.response.send_message("❌ Nur für Server-Admins.", ephemeral=True)

            async with session_scope() as session:
                settings = await get_settings(session, interaction.guild.id, interaction.guild.name)
                active_dungeons = (await session.execute(
                    select(Dungeon.name).where(Dungeon.is_active.is_(True)).order_by(Dungeon.sort_order.asc(), Dungeon.name.asc())
                )).scalars().all()

            active_dungeon_list = [name for name in active_dungeons if name]
            e = discord.Embed(title=f"⚙️ Server-Status · {interaction.guild.name}")
            e.add_field(name="Planner Channel", value=_channel_status(interaction.guild, settings.planner_channel_id), inline=False)
            e.add_field(name="Participants Channel", value=_channel_status(interaction.guild, settings.participants_channel_id), inline=False)
            e.add_field(name="Raidlist Channel", value=_channel_status(interaction.guild, settings.raidlist_channel_id), inline=False)
            e.add_field(name="Standard Mindestspieler", value=str(settings.default_min_players), inline=True)
            e.add_field(name="Templates aktiviert", value="✅ Ja" if settings.templates_enabled else "❌ Nein", inline=True)
            e.add_field(
                name="Aktive Dungeons (offene Raids)",
                value="\n".join(f"• {name}" for name in active_dungeon_list[:20]) if active_dungeon_list else "—",
                inline=False,
            )
            await interaction.response.send_message(embed=e, ephemeral=True)

        @self.tree.command(name="help", description="Zeigt verfügbare Commands und Kurzinfos")
        async def help_cmd(interaction: discord.Interaction):
            lines = [
                "**DMW Raid Bot Hilfe**",
                "`/raidplan` - Raid erstellen",
                "`/raidlist` - Raidlist sofort aktualisieren",
                "`/settings` - Bot-Channels konfigurieren",
                "`/dungeonlist` - aktive Dungeons anzeigen",
                "`/help2` - Schritt-für-Schritt Raid-Anleitung im Channel posten",
            ]

            if _is_server_admin(interaction):
                lines.extend([
                    "`/status` - Kern-Konfiguration prüfen",
                    "`/cancel_all_raids` - alle offenen Raids stoppen",
                    "`/template_config` - Auto-Templates aktivieren/deaktivieren",
                    "`/attendance_list` - Attendance pro Raid anzeigen",
                    "`/attendance_mark` - Attendance setzen",
                    "`/purge` - letzte N Nachrichten löschen",
                    "`/purgebot` - Bot-Nachrichten channelweit/serverweit löschen",
                    "`/restart` - Bot neu starten",
                ])

            if getattr(interaction.user, "id", None) == 403988960638009347:
                lines.extend([
                    "`/remote_guilds` - bekannte Guilds anzeigen (privileged)",
                    "`/remote_cancel_all_raids` - Remote-Cancel (privileged)",
                    "`/remote_raidlist` - Remote-Raidlist Refresh (privileged)",
                    "`/backup_db` - Failsafe: DB SQL Backup sofort (privileged)",
                ])

            lines.append("")
            lines.append(f"Stale-Raid Auto-Cleanup: offen > {STALE_RAID_HOURS}h wird automatisch beendet.")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @self.tree.command(name="help2", description="Postet eine Schritt-für-Schritt Raid-Anleitung in diesen Channel")
        async def help2_cmd(interaction: discord.Interaction):
            if interaction.channel is None:
                return await interaction.response.send_message("❌ Kein Channel gefunden.", ephemeral=True)

            guide = (
                "## 🧭 DMW Raid Bot – Schritt-für-Schritt\n"
                "1. **Settings setzen**: Nutze `/settings` und wähle mindestens Planner + Participants Channel.\n"
                "2. **Dungeon prüfen**: Mit `/dungeonlist` siehst du alle aktiven Dungeons.\n"
                "3. **Raid erstellen**: Starte `/raidplan`, wähle Dungeon, Tage, Uhrzeiten und Mindestspieler.\n"
                "4. **Abstimmen lassen**: Mitglieder stimmen im Raid-Post per Auswahlfeldern für Tage/Uhrzeiten ab.\n"
                "5. **Raid verwalten**: Der Bot aktualisiert Teilnehmer-/Slot-Listen automatisch anhand der Votes.\n"
                "6. **Raidliste aktualisieren**: Bei Bedarf `/raidlist` ausführen.\n"
                "7. **Raid beenden**: Der Ersteller klickt auf **\"Raid beenden\"** im Raid-Post.\n"
                "8. **Admin-Notfall**: `/cancel_all_raids` bricht alle offenen Raids im aktuellen Server ab."
            )

            try:
                await interaction.channel.send(guide)
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Ich darf in diesem Channel nicht schreiben.", ephemeral=True)

            await interaction.response.send_message("✅ Anleitung wurde in diesen Channel gepostet.", ephemeral=True)

        @self.tree.command(name="restart", description="Startet den Bot-Prozess neu")
        @admin_or_privileged_check()
        async def restart_cmd(interaction: discord.Interaction):
            await interaction.response.send_message("♻️ Neustart wird ausgeführt …", ephemeral=True)
            asyncio.create_task(self._restart_process())

        if self.stale_raid_task is None or self.stale_raid_task.done():
            self.stale_raid_task = asyncio.create_task(self._stale_raid_worker())
        if self.voice_xp_task is None or self.voice_xp_task.done():
            self.voice_xp_task = asyncio.create_task(self._voice_xp_worker())
        if self.self_test_task is None or self.self_test_task.done():
            self.self_test_task = asyncio.create_task(self._self_test_worker())
        if self.backup_task is None or self.backup_task.done():
            self.backup_task = asyncio.create_task(self._backup_worker())

    async def restore_persistent_raid_views(self) -> None:
        """Re-register persistent raid planner views after bot restart."""
        restored = 0

        async with session_scope() as session:
            open_raids = (await session.execute(
                select(Raid).where(Raid.status == "open")
            )).scalars().all()

            for raid in open_raids:
                if not raid.message_id:
                    continue

                days, times = await get_options(session, raid.id)
                if not days or not times:
                    continue

                self.add_view(RaidVoteView(raid.id, days, times))
                restored += 1

        if restored:
            log.info("Restored %s persistent raid views", restored)



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


    async def _run_backup_once(self) -> str:
        self.enqueue_discord_log("[backup] Auto-Backup gestartet.")
        log.info("Repository SQL auto-backup started")
        path = await export_database_to_sql()
        self.enqueue_discord_log(f"[backup] Auto-Backup abgeschlossen: {path.as_posix()}")
        log.info("Repository SQL backup written to %s", path.as_posix())
        return path.as_posix()

    async def _backup_worker(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._run_backup_once()
            except Exception:
                log.exception("Repository SQL backup worker failed")
            await asyncio.sleep(max(300, BACKUP_INTERVAL_SECONDS))

    async def _voice_xp_worker(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._award_voice_xp_once()
            except Exception:
                log.exception("Voice XP worker failed")
            await asyncio.sleep(VOICE_XP_CHECK_SECONDS)

    async def _run_self_tests_once(self):
        registered, missing, unexpected = self._command_registry_health()
        if missing:
            raise RuntimeError(f"Missing commands: {', '.join(missing)}")
        if unexpected:
            raise RuntimeError(f"Unexpected commands: {', '.join(unexpected)}")

        registered_commands = set(registered)

        async with session_scope() as session:
            guild_count = int((await session.execute(select(func.count()).select_from(GuildSettings))).scalar_one())
            raid_count = int((await session.execute(select(func.count()).select_from(Raid))).scalar_one())

        self.last_self_test_ok_at = datetime.utcnow()
        self.last_self_test_error = None
        log.info(
            "Self-test passed (commands=%s, guild_settings_rows=%s, raids_rows=%s)",
            len(registered_commands),
            guild_count,
            raid_count,
        )

    async def _self_test_worker(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._run_self_tests_once()
            except Exception as exc:
                self.last_self_test_error = str(exc)
                log.exception("Background self-test failed")
            await asyncio.sleep(max(30, SELF_TEST_INTERVAL_SECONDS))

    async def _award_voice_xp_once(self):
        now = datetime.utcnow()

        for guild in self.guilds:
            async with session_scope() as session:
                for voice_channel in guild.voice_channels:
                    for member in voice_channel.members:
                        if member.bot:
                            continue

                        key = (guild.id, member.id)
                        last_award = self.voice_xp_last_award.get(key)

                        if last_award is None:
                            self.voice_xp_last_award[key] = now
                            continue

                        if now - last_award < VOICE_XP_AWARD_INTERVAL:
                            continue

                        user_level = await session.get(UserLevel, (guild.id, member.id))
                        if user_level is None:
                            user_level = UserLevel(
                                guild_id=guild.id,
                                user_id=member.id,
                                username=_member_username_in_guild(member),
                                xp=0,
                                level=0,
                            )
                            session.add(user_level)

                        user_level.username = _member_username_in_guild(member)
                        user_level.xp += 1
                        user_level.level = calculate_level_from_xp(user_level.xp)
                        self.voice_xp_last_award[key] = now

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot or member.guild is None:
            return

        key = (member.guild.id, member.id)
        if after.channel is None:
            self.voice_xp_last_award.pop(key, None)
        elif before.channel is None:
            self.voice_xp_last_award[key] = datetime.utcnow()

    async def on_message(self, message: discord.Message):
        if not ENABLE_MESSAGE_CONTENT_INTENT:
            return

        if message.author.bot:
            return

        if (
            self.log_channel is not None
            and message.guild is not None
            and message.channel.id == self.log_channel.id
            and isinstance(message.author, discord.Member)
            and message.author.guild_permissions.administrator
        ):
            executed = await self._execute_console_command(message)
            if executed:
                return

        if message.guild is not None:
            gained_xp = 10
            async with session_scope() as session:
                user_level = await session.get(UserLevel, (message.guild.id, message.author.id))
                if user_level is None:
                    user_level = UserLevel(
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        username=_member_username_in_guild(message.author),
                        xp=0,
                        level=0,
                    )
                    session.add(user_level)

                user_level.username = _member_username_in_guild(message.author)
                previous_level = user_level.level
                user_level.xp += gained_xp
                user_level.level = calculate_level_from_xp(user_level.xp)

                if user_level.level > previous_level:
                    await message.channel.send(
                        f"🎉 {message.author.mention} ist auf **Level {user_level.level}** aufgestiegen! "
                        f"(XP: {user_level.xp})"
                    )

        if contains_nanomon_keyword(message.content):
            await message.reply(NANOMON_IMAGE_URL, mention_author=False)

        if contains_approved_keyword(message.content):
            await message.reply(APPROVED_GIF_URL, mention_author=False)


    async def on_guild_remove(self, guild: discord.Guild):
        try:
            async with session_scope() as session:
                deleted = await purge_guild_data(session, guild.id)

            self.voice_xp_last_award = {
                key: value for key, value in self.voice_xp_last_award.items() if key[0] != guild.id
            }

            log.info(
                "Removed database data for guild %s after bot removal (raids=%s, user_levels=%s, guild_settings=%s)",
                guild.id,
                deleted["raids"],
                deleted["user_levels"],
                deleted["guild_settings"],
            )
        except Exception:
            log.exception("Failed to remove database data for removed guild %s", guild.id)

    async def on_guild_join(self, guild: discord.Guild):
        try:
            async with session_scope() as session:
                await get_settings(session, guild.id, guild.name)
        except Exception:
            log.exception("Failed to update guild settings name for guild %s", guild.id)

        try:
            await self.tree.sync(guild=discord.Object(id=guild.id))
            log.info("Synced commands for newly joined guild %s", guild.id)
        except Exception:
            log.exception("Failed to sync commands for newly joined guild %s", guild.id)

        try:
            await force_raidlist_refresh(self, guild.id)
        except Exception:
            log.exception("Failed to refresh raidlist for newly joined guild %s", guild.id)

    async def _refresh_raidlists_for_all_guilds(self) -> None:
        async def _refresh_one(guild_id: int) -> None:
            try:
                await force_raidlist_refresh(self, guild_id)
            except Exception:
                log.exception("Initial raidlist refresh failed for guild %s", guild_id)

        await asyncio.gather(*(_refresh_one(guild.id) for guild in self.guilds))

    async def _restore_memberlists_for_all_guilds(self) -> None:
        async def _restore_one(guild: discord.Guild, raid_id: int) -> None:
            try:
                await sync_memberlists_for_raid(self, guild, raid_id, ensure_debug_mirror=True)
            except Exception:
                log.exception("Memberlist restore failed for guild %s raid %s", guild.id, raid_id)

        tasks: list[asyncio.Task] = []
        for guild in self.guilds:
            async with session_scope() as session:
                raid_ids = (
                    await session.execute(
                        select(Raid.id).where(Raid.guild_id == guild.id, Raid.status == "open")
                    )
                ).scalars().all()

            tasks.extend(asyncio.create_task(_restore_one(guild, int(raid_id))) for raid_id in raid_ids)

        if tasks:
            await asyncio.gather(*tasks)

    async def on_ready(self):
        if not self._startup_guild_cleanup_done:
            await self._cleanup_removed_guild_data_on_startup()
            self._startup_guild_cleanup_done = True

        if self.log_channel is None:
            self.log_channel = await self._resolve_log_channel()

        if self.log_forwarder_task is None or self.log_forwarder_task.done():
            self.log_forwarder_task = asyncio.create_task(self._log_forwarder_worker())

        if self.log_channel is not None:
            while self.pending_log_buffer:
                self.log_forward_queue.put_nowait(self.pending_log_buffer.popleft())
            self.log_forward_queue.put_nowait("Discord live logging initialisiert.")

        if not self._ready_sync_done:
            await self._sync_commands_for_known_guilds()
            self._ready_sync_done = True

        log.info("Logged in as %s", self.user)
        if not self._initial_raidlist_refresh_done:
            await self._refresh_raidlists_for_all_guilds()
            self._initial_raidlist_refresh_done = True

        if not self._initial_memberlist_restore_done:
            await self._restore_memberlists_for_all_guilds()
            self._initial_memberlist_restore_done = True

    async def close(self):
        log.removeHandler(self._discord_log_handler)
        if self.stale_raid_task and not self.stale_raid_task.done():
            self.stale_raid_task.cancel()
        if self.voice_xp_task and not self.voice_xp_task.done():
            self.voice_xp_task.cancel()
        if self.self_test_task and not self.self_test_task.done():
            self.self_test_task.cancel()
        if self.backup_task and not self.backup_task.done():
            self.backup_task.cancel()
        if self.log_forwarder_task and not self.log_forwarder_task.done():
            self.log_forwarder_task.cancel()
        await super().close()

client = RaidBot()

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

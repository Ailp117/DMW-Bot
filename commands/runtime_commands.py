from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.runtime_helpers import (
    DEFAULT_PRIVILEGED_USER_ID,
    _admin_or_privileged_check,
    _on_off,
    _safe_followup,
    _safe_send_initial,
    _settings_embed,
)
from bot.discord_api import app_commands, discord
from services.admin_service import list_active_dungeons
from services.backup_service import export_rows_to_sql
from services.raid_service import build_raid_plan_defaults
from services.settings_service import set_templates_enabled
from services.update_service import pull_repo_update
from views.raid_views import RaidDateSelectionView, SettingsView

if TYPE_CHECKING:
    from bot.runtime import RewriteDiscordBot


log = logging.getLogger("dmw.runtime")


def register_runtime_commands(bot: "RewriteDiscordBot") -> None:
    def _can_use_privileged(interaction: Any) -> bool:
        return bot._is_privileged_user(getattr(getattr(interaction, "user", None), "id", None))

    async def _require_privileged(interaction: Any) -> bool:
        if _can_use_privileged(interaction):
            return True
        user_id = getattr(getattr(interaction, "user", None), "id", None)
        log.warning(
            "Privileged command denied user_id=%s configured_user_id=%s owner_ids=%s command=%s",
            user_id,
            int(getattr(bot.config, "privileged_user_id", DEFAULT_PRIVILEGED_USER_ID)),
            sorted(bot._application_owner_ids),
            getattr(getattr(interaction, "command", None), "name", None),
        )
        await bot._reply(interaction, "❌ Nur für den Debug-Owner erlaubt.", ephemeral=True)
        return False

    @bot.tree.command(
        name="settings",
        description="Setzt Umfragen-/Teilnehmerlisten-/Raidlist-/Kalender-Channel und Feature-Toggles.",
    )
    @_admin_or_privileged_check()
    async def settings_cmd(interaction):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        async with bot._state_lock:
            settings = bot.repo.ensure_settings(interaction.guild.id, interaction.guild.name)
            feature_settings = bot._get_guild_feature_settings(interaction.guild.id)
            calendar_channel_id = bot._get_raid_calendar_channel_id(interaction.guild.id)
        view = SettingsView(bot, guild_id=interaction.guild.id)
        sent = await _safe_send_initial(
            interaction,
            "Settings",
            ephemeral=True,
            embed=_settings_embed(
                settings,
                interaction.guild.name,
                feature_settings,
                raid_calendar_channel_id=calendar_channel_id,
            ),
            view=view,
        )
        if not sent:
            await bot._reply(interaction, "Settings-Ansicht konnte nicht geoeffnet werden.", ephemeral=True)

    @bot.tree.command(name="status", description="Zeigt den aktuellen Bot-Status")
    async def status_cmd(interaction):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        settings = bot.repo.ensure_settings(interaction.guild.id, interaction.guild.name)
        feature_settings = bot._get_guild_feature_settings(interaction.guild.id)
        calendar_channel_id = bot._get_raid_calendar_channel_id(interaction.guild.id)
        calendar_message_row = bot._get_raid_calendar_state_row(interaction.guild.id)
        open_raids = bot.repo.list_open_raids(interaction.guild.id)
        self_test_ok = bot.last_self_test_ok_at.isoformat() if bot.last_self_test_ok_at else "-"
        self_test_err = bot.last_self_test_error or "-"
        await bot._reply(
            interaction,
            (
                f"Guild: **{interaction.guild.name}**\n"
                f"Privileged User ID (configured): `{int(getattr(bot.config, 'privileged_user_id', DEFAULT_PRIVILEGED_USER_ID))}`\n"
                f"Level Persist Interval (s): `{int(bot.config.level_persist_interval_seconds)}`\n"
                f"Levelsystem: `{_on_off(feature_settings.leveling_enabled)}`\n"
                f"Levelup Nachrichten: `{_on_off(feature_settings.levelup_messages_enabled)}`\n"
                f"Nanomon Reply: `{_on_off(feature_settings.nanomon_reply_enabled)}`\n"
                f"Approved Reply: `{_on_off(feature_settings.approved_reply_enabled)}`\n"
                f"Raid Reminder: `{_on_off(feature_settings.raid_reminder_enabled)}`\n"
                f"Message XP Interval (s): `{int(feature_settings.message_xp_interval_seconds)}`\n"
                f"Levelup Cooldown (s): `{int(feature_settings.levelup_message_cooldown_seconds)}`\n"
                f"Umfragen Channel: `{settings.planner_channel_id}`\n"
                f"Raid Teilnehmerlisten Channel: `{settings.participants_channel_id}`\n"
                f"Raidlist Channel: `{settings.raidlist_channel_id}`\n"
                f"Raidlist Message: `{settings.raidlist_message_id}`\n"
                f"Raid Kalender Channel: `{calendar_channel_id}`\n"
                f"Raid Kalender Message: `{int(getattr(calendar_message_row, 'message_id', 0) or 0)}`\n"
                f"Open Raids: `{len(open_raids)}`\n"
                f"Self-Test OK: `{self_test_ok}`\n"
                f"Self-Test Error: `{self_test_err}`"
            ),
            ephemeral=True,
        )

    @bot.tree.command(name="id", description="Postet einen XP-Ausweis als Embed im aktuellen Channel")
    async def id_cmd(interaction):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        target_user = interaction.user
        embed = bot._build_user_id_card_embed(
            guild_id=int(interaction.guild.id),
            guild_name=(interaction.guild.name or "").strip() or f"Guild {interaction.guild.id}",
            user=target_user,
        )
        posted = await _safe_send_initial(interaction, None, ephemeral=False, embed=embed)
        if not posted:
            await bot._reply(interaction, "Ausweis konnte nicht gepostet werden.", ephemeral=True)

    @bot.tree.command(name="help", description="Zeigt verfuegbare Commands")
    async def help_cmd(interaction):
        names = bot._public_help_command_names()
        await bot._reply(
            interaction,
            "Verfuegbare Commands:\n" + "\n".join(f"- /{name}" for name in names),
            ephemeral=True,
        )

    @bot.tree.command(name="help2", description="Postet eine kurze Anleitung")
    async def help2_cmd(interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await bot._reply(interaction, "Nur im Textchannel nutzbar.", ephemeral=True)
            return
        await bot._send_channel_message(
            interaction.channel,
            content=(
                "1) /settings\n"
                "2) /raidplan\n"
                "3) Abstimmung im Raid-Post per Selects\n"
                "4) /raidlist fuer Live-Refresh\n"
                "5) Raid beenden ueber Button oder /raid_finish\n"
                "6) /purgebot scope=channel|server fuer Bot-Nachrichten-Reset"
            ),
        )
        await bot._reply(interaction, "Anleitung gepostet.", ephemeral=True)

    @bot.tree.command(name="restart", description="Stoppt den Prozess (Runner startet neu)")
    async def restart_cmd(interaction):
        if not await _require_privileged(interaction):
            return
        await bot._reply(interaction, "Neustart wird eingeleitet.", ephemeral=True)
        await bot.close()

    @bot.tree.command(
        name="restart_update",
        description="Fuehrt `git pull --ff-only` aus und startet den Bot neu (privileged).",
    )
    async def restart_update_cmd(interaction):
        if not await _require_privileged(interaction):
            return

        await bot._defer(interaction, ephemeral=True)
        result = await asyncio.to_thread(
            pull_repo_update,
            repo_dir=Path.cwd(),
            timeout_seconds=60,
        )
        if not result.ok:
            await _safe_followup(
                interaction,
                f"Update fehlgeschlagen. Kein Neustart.\n{result.detail}",
                ephemeral=True,
            )
            return

        state = "Neue Commits eingespielt." if result.changed else "Kein neuer Commit gefunden."
        await _safe_followup(
            interaction,
            f"{state}\n{result.detail}\nNeustart wird eingeleitet.",
            ephemeral=True,
        )
        await bot.close()

    @bot.tree.command(name="dungeonlist", description="Aktive Dungeons")
    async def dungeonlist_cmd(interaction):
        names = list_active_dungeons(bot.repo)
        if not names:
            await bot._reply(interaction, "Keine aktiven Dungeons.", ephemeral=True)
            return
        await bot._reply(interaction, "\n".join(f"- {name}" for name in names), ephemeral=True)

    @bot.tree.command(name="raidplan", description="Erstellt einen Raid Plan (Datumsauswahl + Modal)")
    @app_commands.describe(dungeon="Dungeon Name")
    async def raidplan_cmd(interaction, dungeon: str):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await bot._reply(interaction, "Nur im Text-Serverchannel nutzbar.", ephemeral=True)
            return

        async with bot._state_lock:
            settings = bot.repo.ensure_settings(interaction.guild.id, interaction.guild.name)
            if not settings.planner_channel_id or not settings.participants_channel_id:
                await bot._reply(
                    interaction,
                    "Bitte zuerst /settings konfigurieren (Umfragen + Teilnehmerlisten Channel).",
                    ephemeral=True,
                )
                return

            try:
                defaults = build_raid_plan_defaults(
                    bot.repo,
                    guild_id=interaction.guild.id,
                    guild_name=interaction.guild.name,
                    dungeon_name=dungeon,
                )
            except ValueError as exc:
                await bot._reply(interaction, f"Fehler: {exc}", ephemeral=True)
                return

        view = RaidDateSelectionView(
            bot,
            owner_user_id=interaction.user.id,
            guild_id=interaction.guild.id,
            guild_name=interaction.guild.name,
            channel_id=int(settings.planner_channel_id),
            dungeon_name=dungeon,
            default_days=defaults.days,
            default_times=defaults.times,
            default_min_players=defaults.min_players,
        )
        sent = await _safe_send_initial(
            interaction,
            (
                "Waehle ein oder mehrere Daten aus und klicke dann auf "
                "`Weiter (Uhrzeiten + Min Spieler)`."
            ),
            ephemeral=True,
            view=view,
        )
        if not sent:
            await bot._reply(interaction, "Datumsauswahl konnte nicht geoeffnet werden.", ephemeral=True)

    @raidplan_cmd.autocomplete("dungeon")
    async def raidplan_dungeon_autocomplete(interaction, current: str):
        query = (current or "").strip().lower()
        rows = bot.repo.list_active_dungeons()
        if query:
            rows = [row for row in rows if query in row.name.lower()]
        return [app_commands.Choice(name=row.name, value=row.name) for row in rows[:25]]

    @bot.tree.command(name="raid_finish", description="Schliesst einen Raid und erstellt Attendance")
    async def raid_finish_cmd(interaction, raid_id: int):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        raid = bot._find_open_raid_by_display_id(interaction.guild.id, raid_id)
        if raid is None:
            await bot._reply(interaction, f"Kein offener Raid mit ID `{raid_id}` gefunden.", ephemeral=True)
            return
        await bot._finish_raid_interaction(interaction, raid_id=raid.id, deferred=False)

    @bot.tree.command(name="raidlist", description="Aktualisiert die Raidlist Nachricht")
    async def raidlist_cmd(interaction):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return
        async with bot._state_lock:
            await bot._force_raidlist_refresh(interaction.guild.id)
            persisted = await bot._persist(dirty_tables={"settings", "debug_cache"})
        if not persisted:
            await bot._reply(interaction, "Raidlist Refresh fehlgeschlagen (DB).", ephemeral=True)
            return
        await bot._reply(interaction, "Raidlist aktualisiert.", ephemeral=True)

    @bot.tree.command(
        name="raidcalendar_rebuild",
        description="Loescht den alten Raid-Kalender und baut ihn im konfigurierten Channel neu auf.",
    )
    @_admin_or_privileged_check()
    async def raidcalendar_rebuild_cmd(interaction):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return
        await bot._defer(interaction, ephemeral=True)

        guild_id = int(interaction.guild.id)
        async with bot._state_lock:
            configured_channel_id = bot._get_raid_calendar_channel_id(guild_id)
            if configured_channel_id is None:
                rebuilt = False
                persisted = True
            else:
                rebuilt = await bot._rebuild_raid_calendar_message_for_guild(guild_id)
                persisted = await bot._persist(dirty_tables={"debug_cache"})

        if configured_channel_id is None:
            await _safe_followup(
                interaction,
                "Raid Kalender Channel ist nicht gesetzt. Bitte zuerst in /settings konfigurieren.",
                ephemeral=True,
            )
            return
        if not persisted:
            await _safe_followup(
                interaction,
                "Kalender neu aufgebaut, aber DB-Speicherung fehlgeschlagen.",
                ephemeral=True,
            )
            return
        if rebuilt:
            await _safe_followup(
                interaction,
                f"Raid Kalender wurde neu aufgebaut (Channel `{configured_channel_id}`).",
                ephemeral=True,
            )
            return
        await _safe_followup(
            interaction,
            "Raid Kalender konnte nicht neu aufgebaut werden (Channel nicht erreichbar).",
            ephemeral=True,
        )

    @bot.tree.command(name="cancel_all_raids", description="Bricht alle offenen Raids ab")
    @_admin_or_privileged_check()
    async def cancel_all_raids_cmd(interaction):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return
        async with bot._state_lock:
            count = await bot._cancel_raids_for_guild(interaction.guild.id, reason="abgebrochen")
            persisted = await bot._persist()
        if not persisted:
            await bot._reply(interaction, "Raids gecancelt, aber DB-Speicherung fehlgeschlagen.", ephemeral=True)
            return
        await bot._reply(interaction, f"{count} offene Raids gecancelt.", ephemeral=True)

    @bot.tree.command(name="template_config", description="Aktiviert/Deaktiviert Templates")
    @_admin_or_privileged_check()
    @app_commands.describe(enabled="Templates aktiv")
    async def template_config_cmd(interaction, enabled: bool):
        if not interaction.guild:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return
        async with bot._state_lock:
            row = set_templates_enabled(bot.repo, interaction.guild.id, interaction.guild.name, enabled)
            persisted = await bot._persist(dirty_tables={"settings"})
        if not persisted:
            await bot._reply(interaction, "Template-Config konnte nicht gespeichert werden.", ephemeral=True)
            return
        await bot._reply(interaction, f"templates_enabled={row.templates_enabled}", ephemeral=True)

    @bot.tree.command(name="purge", description="Loescht letzte N Nachrichten")
    @_admin_or_privileged_check()
    async def purge_cmd(interaction, amount: int = 10):
        channel = interaction.channel
        purge_fn = getattr(channel, "purge", None)
        if channel is None or not callable(purge_fn):
            await bot._reply(interaction, "Nur im Textchannel nutzbar.", ephemeral=True)
            return
        await bot._defer(interaction, ephemeral=True)
        amount = max(1, min(100, int(amount)))
        deleted_result = await bot._await_if_needed(purge_fn(limit=amount))
        try:
            deleted_count = len(deleted_result)
        except TypeError:
            deleted_count = 0
        await _safe_followup(interaction, f"{deleted_count} Nachrichten geloescht.", ephemeral=True)

    @bot.tree.command(name="purgebot", description="Loescht Bot-Nachrichten im Channel oder serverweit")
    @_admin_or_privileged_check()
    @app_commands.describe(
        scope="`channel` = aktueller Channel, `server` = alle Textchannels",
        limit="Max. gepruefte Nachrichten je Channel (1-5000)",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="channel", value="channel"),
            app_commands.Choice(name="server", value="server"),
        ]
    )
    async def purgebot_cmd(interaction, scope: app_commands.Choice[str], limit: int = 500):
        if interaction.guild is None:
            await bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return
        await bot._defer(interaction, ephemeral=True)

        limit = max(1, min(5000, int(limit)))
        me = interaction.guild.me or interaction.guild.get_member(getattr(bot.user, "id", 0))
        if me is None:
            await _safe_followup(interaction, "Bot-Mitglied im Server nicht gefunden.", ephemeral=True)
            return

        channels: list[Any]
        if scope.value == "channel":
            if not isinstance(interaction.channel, discord.TextChannel):
                await _safe_followup(interaction, "Nur im Textchannel nutzbar.", ephemeral=True)
                return
            channels = [interaction.channel]
        else:
            channels = [
                channel
                for channel in interaction.guild.text_channels
                if channel.permissions_for(me).read_message_history
            ]

        total_deleted = 0
        touched_channels = 0
        scan_history = scope.value == "channel"
        scan_limit = limit if scan_history else min(limit, 150)
        for channel in channels:
            try:
                perms = channel.permissions_for(me)
                if not (perms.read_message_history and perms.manage_messages):
                    continue
                deleted_here = await bot._delete_bot_messages_in_channel(
                    channel,
                    history_limit=scan_limit,
                    scan_history=scan_history,
                )
                if deleted_here > 0:
                    total_deleted += deleted_here
                    touched_channels += 1
            except Exception:
                log.exception(
                    "purgebot failed for channel_id=%s guild_id=%s",
                    getattr(channel, "id", None),
                    getattr(interaction.guild, "id", None),
                )
                continue

        where = "aktueller Channel" if scope.value == "channel" else f"{touched_channels} Channel(s)"
        await _safe_followup(
            interaction,
            (
                f"{total_deleted} Bot-Nachrichten geloescht ({where}, "
                f"Limit je Channel: {scan_limit}, History-Scan: {'an' if scan_history else 'reduziert'})."
            ),
            ephemeral=True,
        )

    @bot.tree.command(name="remote_guilds", description="Zeigt bekannte Server für Fernwartung an (privileged).")
    async def remote_guilds_cmd(interaction):
        if not await _require_privileged(interaction):
            return
        await bot._defer(interaction, ephemeral=True)
        guilds = sorted(bot.guilds, key=lambda guild: ((guild.name or "").casefold(), int(guild.id)))
        if not guilds:
            await _safe_followup(interaction, "Keine verbundenen Server gefunden.", ephemeral=True)
            return
        lines: list[str] = []
        for guild in guilds[:50]:
            name = (guild.name or "").strip() or "(unbekannt)"
            lines.append(f"• **{name}**")
        await _safe_followup(interaction, "\n".join(lines), ephemeral=True)

    @bot.tree.command(name="remote_cancel_all_raids", description="Fernwartung: Alle offenen Raids eines Servers abbrechen.")
    @app_commands.describe(guild_name="Zielservername (Autocomplete)")
    async def remote_cancel_all_raids_cmd(interaction, guild_name: str):
        if not await _require_privileged(interaction):
            return
        target, err = bot._resolve_remote_target_by_name(guild_name)
        if target is None:
            await bot._reply(interaction, err or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)
            return

        await bot._defer(interaction, ephemeral=True)
        async with bot._state_lock:
            count = await bot._cancel_raids_for_guild(target, reason="remote-abgebrochen")
            persisted = await bot._persist()

        if not persisted:
            await _safe_followup(
                interaction,
                "Remote-Cancel ausgeführt, aber DB-Speicherung fehlgeschlagen.",
                ephemeral=True,
            )
            return
        target_guild = bot.get_guild(target)
        target_name = (target_guild.name if target_guild else None) or guild_name
        await _safe_followup(interaction, f"✅ {count} offene Raids in **{target_name}** abgebrochen.", ephemeral=True)

    @remote_cancel_all_raids_cmd.autocomplete("guild_name")
    async def remote_cancel_all_raids_autocomplete(interaction, current: str):
        if not _can_use_privileged(interaction):
            return []
        return bot._remote_guild_autocomplete_choices(current)

    @bot.tree.command(name="remote_raidlist", description="Fernwartung: Raidlist eines Zielservers neu aufbauen.")
    @app_commands.describe(guild_name="Zielservername (Autocomplete)")
    async def remote_raidlist_cmd(interaction, guild_name: str):
        if not await _require_privileged(interaction):
            return
        target, err = bot._resolve_remote_target_by_name(guild_name)
        if target is None:
            await bot._reply(interaction, err or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)
            return

        await bot._defer(interaction, ephemeral=True)
        async with bot._state_lock:
            await bot._refresh_raidlist_for_guild(target, force=True)
            await bot._refresh_raid_calendar_for_guild(target, force=True)
            persisted = await bot._persist(dirty_tables={"settings", "debug_cache"})

        if not persisted:
            await _safe_followup(interaction, "Remote-Raidlist-Refresh fehlgeschlagen (DB).", ephemeral=True)
            return

        target_guild = bot.get_guild(target)
        target_name = (target_guild.name if target_guild else None) or guild_name
        await _safe_followup(interaction, f"✅ Raidlist für **{target_name}** aktualisiert.", ephemeral=True)

    @remote_raidlist_cmd.autocomplete("guild_name")
    async def remote_raidlist_autocomplete(interaction, current: str):
        if not _can_use_privileged(interaction):
            return []
        return bot._remote_guild_autocomplete_choices(current)

    @bot.tree.command(
        name="remote_rebuild_memberlists",
        description="Fernwartung: Teilnehmerlisten eines Zielservers vollständig neu aufbauen.",
    )
    @app_commands.describe(guild_name="Zielservername (Autocomplete)")
    async def remote_rebuild_memberlists_cmd(interaction, guild_name: str):
        if not await _require_privileged(interaction):
            return
        target, err = bot._resolve_remote_target_by_name(guild_name)
        if target is None:
            await bot._reply(interaction, err or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)
            return

        await bot._defer(interaction, ephemeral=True)
        async with bot._state_lock:
            settings = bot.repo.ensure_settings(target)
            if not settings.participants_channel_id:
                await _safe_followup(
                    interaction,
                    "❌ Zielserver hat keinen Participants-Channel konfiguriert.",
                    ephemeral=True,
                )
                return
            participants_channel = await bot._get_text_channel(settings.participants_channel_id)
            if participants_channel is None:
                await _safe_followup(
                    interaction,
                    "❌ Participants-Channel des Zielservers ist nicht erreichbar.",
                    ephemeral=True,
                )
                return

            stats = await bot._rebuild_memberlists_for_guild(target, participants_channel=participants_channel)
            persisted = await bot._persist()

        if not persisted:
            await _safe_followup(
                interaction,
                "Remote-Rebuild ausgeführt, aber DB-Speicherung fehlgeschlagen.",
                ephemeral=True,
            )
            return

        target_guild = bot.get_guild(target)
        target_name = (target_guild.name if target_guild else None) or guild_name
        await _safe_followup(
            interaction,
            (
                f"✅ Teilnehmerlisten für **{target_name}** neu aufgebaut.\n"
                f"Raids: `{stats.raids}`\n"
                f"Cleared Slot Rows: `{stats.cleared_slot_rows}`\n"
                f"Deleted Slot Messages: `{stats.deleted_slot_messages}`\n"
                f"Deleted Legacy Bot Messages: `{stats.deleted_legacy_messages}`\n"
                f"Created: `{stats.created}` Updated: `{stats.updated}` Deleted: `{stats.deleted}`"
            ),
            ephemeral=True,
        )

    @remote_rebuild_memberlists_cmd.autocomplete("guild_name")
    async def remote_rebuild_memberlists_autocomplete(interaction, current: str):
        if not _can_use_privileged(interaction):
            return []
        return bot._remote_guild_autocomplete_choices(current)

    @bot.tree.command(name="backup_db", description="Schreibt ein SQL Backup")
    async def backup_db_cmd(interaction):
        if not await _require_privileged(interaction):
            return
        await bot._defer(interaction, ephemeral=True)
        log.info(
            "Manual backup requested by user_id=%s guild_id=%s",
            getattr(interaction.user, "id", None),
            getattr(getattr(interaction, "guild", None), "id", None),
        )

        try:
            async with bot._state_lock:
                rows = bot._snapshot_rows_by_table()
            out = await export_rows_to_sql(Path("backups/db_backup.sql"), rows_by_table=rows)
        except Exception:
            log.exception("Manual backup failed")
            await _safe_followup(interaction, "Backup fehlgeschlagen. Bitte Logs pruefen.", ephemeral=True)
            return

        log.info("Manual backup completed: %s", out.as_posix())
        await _safe_followup(interaction, f"Backup geschrieben: {out.as_posix()}", ephemeral=True)

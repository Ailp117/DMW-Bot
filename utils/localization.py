"""Localization system für Deutsch/English."""
from __future__ import annotations

from typing import Literal

Language = Literal["de", "en"]

# Alle Bot-Nachrichten zentralisiert
STRINGS: dict[Language, dict[str, str]] = {
    "de": {
        # Settings
        "settings_title": "⚙️ Bot Einstellungen",
        "settings_desc": "Verwalte die Konfiguration des Raid Bots",
        "settings_channels": "📌 Channels",
        "settings_features": "⚡ Features",
        "settings_intervals": "⏲️ Intervalle",
        "settings_language": "🌍 Sprache",
        "settings_footer": "Ändere Einstellungen über die Menüs unten",
        "settings_saved": "Settings gespeichert",
        "settings_reset": "Alle Einstellungen auf Standard zurückgesetzt.\nKlicke 'Speichern' um die Änderungen zu übernehmen.",
        
        # Channels
        "channel_planner": "📋 Umfragen",
        "channel_participants": "👥 Teilnehmerlisten",
        "channel_raidlist": "📊 Raidliste",
        "channel_not_set": "❌ *Nicht gesetzt*",
        "channel_select_planner": "Umfragen Channel wählen",
        "channel_select_participants": "Teilnehmerlisten Channel wählen",
        "channel_select_raidlist": "Raidlist Channel wählen",
        "channel_set_planner": "📋 Umfragen Channel gesetzt",
        "channel_set_participants": "👥 Teilnehmerlisten Channel gesetzt",
        "channel_set_raidlist": "📊 Raidlist Channel gesetzt",
        
        # Features
        "feature_leveling": "📈 Levelsystem",
        "feature_levelup_msg": "🎉 Levelup Msg",
        "feature_nanomon": "🤖 Nanomon Reply",
        "feature_approved": "✅ Approved Reply",
        "feature_raid_reminder": "⏰ Raid Reminder",
        "feature_auto_reminder": "🔔 Auto Reminder",
        "feature_enabled": "🟢 AN",
        "feature_disabled": "🔴 AUS",
        "features_updated": "✅ {count} Features aktualisiert",
        
        # Intervals
        "interval_xp": "⏱️ XP Interval",
        "interval_cooldown": "⏳ Levelup Cooldown",
        "intervals_title": "Allgemeine Feature Settings",
        "intervals_set": "Intervall-Einstellungen vorgemerkt.",
        "intervals_invalid": "Bitte gueltige Zahlen eingeben.",
        "intervals_too_small": "Werte muessen >= 1 sein.",
        "intervals_too_large": "Werte muessen <= {max} sein.",
        
        # Buttons
        "btn_intervals": "Intervalle einstellen",
        "btn_save": "Speichern",
        "btn_reset": "Zurücksetzen",
        "btn_on": "AN",
        "btn_off": "AUS",
        
        # Status
        "status_title": "🤖 Bot Status",
        "status_section_overview": "ℹ️ Overview",
        "status_section_stats": "📊 Statistik",
        "status_guild": "**Server:** {guild}",
        "status_privileged": "**Privileged User:** `{user_id}`",
        "status_level_interval": "**Level Persist Interval:** `{interval}s`",
        "status_open_raids": "**Offene Raids:** `{count}`",
        "status_leveling": "Levelsystem: {value}\nLevelup Nachrichten: {levelup_msg}\nLevelup Cooldown: `{cooldown}s`\nMessage XP Interval: `{xp_interval}s`",
        "status_features": "Raid Reminder: {reminder}\nAuto Reminder: {auto_reminder}\nNanomon Reply: {nanomon}\nApproved Reply: {approved}",
        "status_channels": "Umfragen: {planner}\nTeilnehmerlisten: {participants}\nRaidlist: {raidlist}\nRaidlist Message: `{raidlist_msg}`",
        "status_health": "{icon} Self-Test OK: `{ok}`\n❌ Fehler: `{error}`",
        "status_footer": "Alle Einstellungen können mit /settings konfiguriert werden.",
        
        # Raidlist
        "raidlist_title": "📋 Raidlist",
        "raidlist_overview": "ℹ️ Overview",
        "raidlist_server": "**Server:** {server}",
        "raidlist_raid_field": "🎮 Raid #{display_id} — {dungeon}",
        "raidlist_minimum": "**Minimum:** `{players}`",
        "raidlist_qualified_slots": "**Qualifizierte Slots:** `{count}`",
        "raidlist_votes": "**Abstimmungen:** `{count}` vollständig",
        "raidlist_timezone": "**Zeitzone:** `{tz}`",
        "raidlist_next_slot": "**Nächster Termin:**",
        "raidlist_next_raid": "Raid `{display_id}` {day} {time}",
        "raidlist_view_raid": "Raid ansehen",
        "raidlist_statistics": "📊 Statistik",
        "raidlist_stats_raids": "**Raids:** `{count}`",
        "raidlist_stats_slots": "**Slots:** `{count}`",
        "raidlist_stats_zone": "**Zone:** `{tz}`",
        "raidlist_next_start": "Nächster Start",
        "raidlist_no_raids": "**Server:** {server}\n**Status:** Keine offenen Raids",
        "raidlist_no_raids_short": "Keine offenen Raids.",
        "footer_auto_updated": "Automatisch aktualisiert • DMW Bot",
        "raidlist_empty": "**Server:** {guild}\n**Status:** Keine offenen Raids",
        
        # Errors
        "error_guild_context": "❌ Ungültiger Guild-Kontext.",
        "error_server_only": "❌ Nur im Server nutzbar.",
        "error_text_channel_only": "❌ Nur im Textchannel nutzbar.",
        "error_no_guild": "❌ Nur im Server nutzbar.",
        "error_modal_failed": "❌ Modal konnte nicht geöffnet werden.",
        "error_settings_failed": "❌ Settings konnten nicht gespeichert werden.",
        "error_privileged_denied": "❌ Nur für den Debug-Owner erlaubt.",
        "error_raid_not_found": "❌ Kein offener Raid mit ID `{raid_id}` gefunden.",
        "error_no_permissions": "❌ Keine ausreichenden Berechtigungen.",
        "error_channel_not_found": "❌ Bot-Mitglied im Server nicht gefunden.",
        "error_settings_missing": "❌ Bitte zuerst /settings konfigurieren (Umfragen + Teilnehmerlisten Channel).",
        "error_participants_missing": "❌ Zielserver hat keinen Participants-Channel konfiguriert.",
        "error_remote_failed": "❌ Zielserver konnte nicht aufgelöst werden.",
        "error_config_error": "❌ Fehler: {error}",
        "error_backup_failed": "❌ Backup fehlgeschlagen. Bitte Logs prüfen.",
        "error_view_unavailable": "❌ Settings View nicht verfügbar.",
        
        # Success
        "success_raidlist_updated": "✅ Raidlist aktualisiert.",
        "success_raid_created": "✅ Raid erstellt: `{raid_id}` {dungeon}",
        "success_raids_cancelled": "✅ {count} offene Raids gecancelt.",
        "success_template_set": "✅ templates_enabled={status}",
        "success_backup_done": "✅ Backup geschrieben: {path}",
        "success_messages_deleted": "✅ {count} Bot-Nachrichten gelöscht ({channels} Kanal/Kanäle)",
        "success_remote_cancelled": "✅ {count} offene Raids in **{guild}** abgebrochen.",
        "success_remote_raidlist": "✅ Raidlist für **{guild}** aktualisiert.",
        "success_remote_rebuild": "✅ Teilnehmerlisten für **{guild}** neu aufgebaut.",
        "success_help_posted": "✅ Anleitung gepostet.",
        "success_shutdown": "✅ Neustart wird eingeleitet.",
        "success_settings_posted": "✅ Settings-Ansicht geöffnet.",
        "success_idcard_posted": "✅ Ausweis gepostet.",
        
        # Common
        "enabled": "aktiviert",
        "disabled": "deaktiviert",
        "not_set": "nicht gesetzt",
        "on": "AN",
        "off": "AUS",
        "yes": "Ja",
        "no": "Nein",
    },
    "en": {
        # Settings
        "settings_title": "⚙️ Bot Settings",
        "settings_desc": "Manage the raid bot configuration",
        "settings_channels": "📌 Channels",
        "settings_features": "⚡ Features",
        "settings_intervals": "⏲️ Intervals",
        "settings_language": "🌍 Language",
        "settings_footer": "Change settings using the menus below",
        "settings_saved": "Settings saved",
        "settings_reset": "All settings reset to defaults.\nClick 'Save' to apply changes.",
        
        # Channels
        "channel_planner": "📋 Planner",
        "channel_participants": "👥 Participants",
        "channel_raidlist": "📊 Raidlist",
        "channel_not_set": "❌ *Not set*",
        "channel_select_planner": "Select planner channel",
        "channel_select_participants": "Select participants channel",
        "channel_select_raidlist": "Select raidlist channel",
        "channel_set_planner": "📋 Planner channel set",
        "channel_set_participants": "👥 Participants channel set",
        "channel_set_raidlist": "📊 Raidlist channel set",
        
        # Features
        "feature_leveling": "📈 Leveling System",
        "feature_levelup_msg": "🎉 Levelup Msg",
        "feature_nanomon": "🤖 Nanomon Reply",
        "feature_approved": "✅ Approved Reply",
        "feature_raid_reminder": "⏰ Raid Reminder",
        "feature_auto_reminder": "🔔 Auto Reminder",
        "feature_enabled": "🟢 ON",
        "feature_disabled": "🔴 OFF",
        "features_updated": "✅ {count} features updated",
        
        # Intervals
        "interval_xp": "⏱️ XP Interval",
        "interval_cooldown": "⏳ Levelup Cooldown",
        "intervals_title": "General Feature Settings",
        "intervals_set": "Interval settings saved.",
        "intervals_invalid": "Please enter valid numbers.",
        "intervals_too_small": "Values must be >= 1.",
        "intervals_too_large": "Values must be <= {max}.",
        
        # Buttons
        "btn_intervals": "Set Intervals",
        "btn_save": "Save",
        "btn_reset": "Reset",
        "btn_on": "ON",
        "btn_off": "OFF",
        
        # Status
        "status_title": "🤖 Bot Status",
        "status_section_overview": "ℹ️ Overview",
        "status_section_stats": "📊 Statistics",
        "status_guild": "**Server:** {guild}",
        "status_privileged": "**Privileged User:** `{user_id}`",
        "status_level_interval": "**Level Persist Interval:** `{interval}s`",
        "status_open_raids": "**Open Raids:** `{count}`",
        "status_leveling": "Leveling System: {value}\nLevelup Messages: {levelup_msg}\nLevelup Cooldown: `{cooldown}s`\nMessage XP Interval: `{xp_interval}s`",
        "status_features": "Raid Reminder: {reminder}\nAuto Reminder: {auto_reminder}\nNanomon Reply: {nanomon}\nApproved Reply: {approved}",
        "status_channels": "Planner: {planner}\nParticipants: {participants}\nRaidlist: {raidlist}\nRaidlist Message: `{raidlist_msg}`",
        "status_health": "{icon} Self-Test OK: `{ok}`\n❌ Error: `{error}`",
        "status_footer": "All settings can be configured with /settings.",
        
        # Raidlist
        "raidlist_title": "📋 Raidlist",
        "raidlist_overview": "ℹ️ Overview",
        "raidlist_server": "**Server:** {server}",
        "raidlist_raid_field": "🎮 Raid #{display_id} — {dungeon}",
        "raidlist_minimum": "**Minimum:** `{players}`",
        "raidlist_qualified_slots": "**Qualified Slots:** `{count}`",
        "raidlist_votes": "**Votes:** `{count}` complete",
        "raidlist_timezone": "**Timezone:** `{tz}`",
        "raidlist_next_slot": "**Next Slot:**",
        "raidlist_next_raid": "Raid `{display_id}` {day} {time}",
        "raidlist_view_raid": "View raid",
        "raidlist_statistics": "📊 Statistics",
        "raidlist_stats_raids": "**Raids:** `{count}`",
        "raidlist_stats_slots": "**Slots:** `{count}`",
        "raidlist_stats_zone": "**Zone:** `{tz}`",
        "raidlist_next_start": "Next Start",
        "raidlist_no_raids": "**Server:** {server}\n**Status:** No open raids",
        "raidlist_no_raids_short": "No open raids.",
        "footer_auto_updated": "Auto-updated • DMW Bot",
        "raidlist_empty": "**Server:** {guild}\n**Status:** No open raids",
        
        # Errors
        "error_guild_context": "❌ Invalid guild context.",
        "error_server_only": "❌ Server only.",
        "error_text_channel_only": "❌ Text channel only.",
        "error_no_guild": "❌ Server only.",
        "error_modal_failed": "❌ Modal could not be opened.",
        "error_settings_failed": "❌ Settings could not be saved.",
        "error_privileged_denied": "❌ Debug owner only.",
        "error_raid_not_found": "❌ No open raid with ID `{raid_id}` found.",
        "error_no_permissions": "❌ Insufficient permissions.",
        "error_channel_not_found": "❌ Bot member not found in server.",
        "error_settings_missing": "❌ Please configure /settings first (Planner + Participants Channel).",
        "error_participants_missing": "❌ Target server has no participants channel configured.",
        "error_remote_failed": "❌ Target server could not be resolved.",
        "error_config_error": "❌ Error: {error}",
        "error_backup_failed": "❌ Backup failed. Please check logs.",
        "error_view_unavailable": "❌ Settings view not available.",
        
        # Success
        "success_raidlist_updated": "✅ Raidlist updated.",
        "success_raid_created": "✅ Raid created: `{raid_id}` {dungeon}",
        "success_raids_cancelled": "✅ {count} open raids cancelled.",
        "success_template_set": "✅ templates_enabled={status}",
        "success_backup_done": "✅ Backup written: {path}",
        "success_messages_deleted": "✅ {count} bot messages deleted ({channels} channel(s))",
        "success_remote_cancelled": "✅ {count} open raids in **{guild}** cancelled.",
        "success_remote_raidlist": "✅ Raidlist for **{guild}** updated.",
        "success_remote_rebuild": "✅ Member lists for **{guild}** rebuilt.",
        "success_help_posted": "✅ Instructions posted.",
        "success_shutdown": "✅ Shutdown initiated.",
        "success_settings_posted": "✅ Settings view opened.",
        "success_idcard_posted": "✅ ID card posted.",
        
        # Common
        "enabled": "enabled",
        "disabled": "disabled",
        "not_set": "not set",
        "on": "ON",
        "off": "OFF",
        "yes": "Yes",
        "no": "No",
    },
}


def get_string(language: Language, key: str, **kwargs) -> str:
    """Holt einen String in der gewünschten Sprache mit optionalen Platzhaltern."""
    text = STRINGS.get(language, {}).get(key, STRINGS["de"].get(key, f"[{key}]"))
    if kwargs:
        return text.format(**kwargs)
    return text


def get_lang(guild_settings) -> Language:
    """Gibt die Sprache für eine Guild zurück (aus settings oder Default: de)."""
    lang = getattr(guild_settings, "language", "de")
    return "de" if lang == "de" else "en"


__all__ = ["Language", "STRINGS", "get_string", "get_lang"]

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from bot.discord_api import discord
from utils.runtime_helpers import (
    DEFAULT_TIMEZONE_NAME,
    FEATURE_INTERVAL_MASK,
    GuildFeatureSettings,
    _member_name,
    _normalize_raid_date_selection,
    _on_off,
    _parse_raid_date_from_label,
    _safe_edit_message,
    _safe_followup,
    _safe_send_initial,
    _settings_embed,
    _upcoming_raid_date_labels,
)
from services.raid_service import create_raid_from_modal, planner_counts, toggle_vote
from services.settings_service import save_channel_settings

if TYPE_CHECKING:
    from bot.runtime import RewriteDiscordBot


class RaidCreateModal(discord.ui.Modal):
    days = discord.ui.TextInput(
        label="Datum (DD.MM.YYYY, comma-separiert)",
        placeholder="z.B. 20.02.2026, 21.02.2026",
        required=True,
        max_length=200,
        row=0,
    )
    times = discord.ui.TextInput(
        label="Uhrzeiten (Komma/Zeilen getrennt)",
        placeholder="z.B. 20:00, 21:00",
        required=True,
        max_length=400,
        row=1,
    )
    min_players = discord.ui.TextInput(
        label="Min Spieler pro Slot (0=ab 1)",
        placeholder="z.B. 3",
        required=True,
        max_length=3,
        row=2,
    )

    def __init__(
        self,
        bot: "RewriteDiscordBot",
        *,
        guild_id: int,
        guild_name: str,
        channel_id: int,
        dungeon_name: str,
        default_times: list[str],
        default_min_players: int,
    ):
        super().__init__(title=f"Raid: {dungeon_name}")
        self.bot = bot
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.channel_id = channel_id
        self.dungeon_name = dungeon_name

        available_days = _upcoming_raid_date_labels()
        day_examples = ", ".join(available_days[:3])
        self.days.placeholder = f"z.B. {day_examples}"

        if default_times:
            self.times.default = ", ".join(default_times)[:400]
        self.min_players.default = str(max(0, int(default_min_players)))

    async def on_submit(self, interaction):
        if not interaction.guild:
            await self.bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)

        selected_days = [d.strip() for d in str(self.days.value).split(",") if d.strip()]
        if not selected_days:
            await _safe_followup(interaction, "Bitte mindestens ein Datum eingeben.", ephemeral=True)
            return
            await self.bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)

        selected_days = [d.strip() for d in str(self.days.value).split(",") if d.strip()]
        if not selected_days:
            await _safe_followup(interaction, "Bitte mindestens ein Datum eingeben.", ephemeral=True)
            return

        try:
            min_players_value = int(str(self.min_players.value).strip())
            if min_players_value < 0:
                raise ValueError
        except ValueError:
            await _safe_followup(interaction, "Min Spieler muss Zahl >= 0 sein.", ephemeral=True)
            return

        async with self.bot._state_lock:
            try:
                result = create_raid_from_modal(
                    self.bot.repo,
                    guild_id=self.guild_id,
                    guild_name=self.guild_name,
                    planner_channel_id=self.channel_id,
                    creator_id=interaction.user.id,
                    dungeon_name=self.dungeon_name,
                    days_input="\n".join(selected_days),
                    times_input=str(self.times.value),
                    min_players_input=str(min_players_value),
                    message_id=0,
                )
            except ValueError as exc:
                await _safe_followup(interaction, f"Fehler: {exc}", ephemeral=True)
                return

            planner_message = await self.bot._refresh_planner_message(result.raid.id)
            if planner_message is None:
                self.bot.repo.delete_raid_cascade(result.raid.id)
                await self.bot._persist()
                await _safe_followup(interaction, "Planner-Post konnte nicht erstellt werden.", ephemeral=True)
                return

            await self.bot._sync_memberlist_messages_for_raid(result.raid.id)
            await self.bot._refresh_raidlist_for_guild(self.guild_id, force=True)
            persisted = await self.bot._persist()
            counts = planner_counts(self.bot.repo, result.raid.id)

        if not persisted:
            await _safe_followup(interaction, "Raid erstellt, aber DB-Speicherung fehlgeschlagen.", ephemeral=True)
            return
        jump_url = getattr(
            planner_message,
            "jump_url",
            f"/channels/{interaction.guild.id}/{self.channel_id}/{planner_message.id}",
        )
        await _safe_followup(
            interaction,
            (
                f"Raid erstellt: `{result.raid.display_id}` {result.raid.dungeon}\n"
                f"Zeitzone: `{DEFAULT_TIMEZONE_NAME}`\n"
                f"Day Votes: {counts['day']}\n"
                f"Time Votes: {counts['time']}\n"
                f"Planner Post: {jump_url}"
            ),
            ephemeral=True,
        )


class SettingsIntervalsModal(discord.ui.Modal):
    message_xp_interval = discord.ui.TextInput(
        label="Message XP Intervall (Sekunden)",
        required=True,
        max_length=5,
    )
    levelup_cooldown = discord.ui.TextInput(
        label="Levelup Cooldown (Sekunden)",
        required=True,
        max_length=5,
    )

    def __init__(self, bot: "RewriteDiscordBot", view: "SettingsView"):
        super().__init__(title="Allgemeine Feature Settings")
        self.bot = bot
        self._view_ref = view
        self.message_xp_interval.default = str(int(view.message_xp_interval_seconds))
        self.levelup_cooldown.default = str(int(view.levelup_message_cooldown_seconds))

    async def on_submit(self, interaction):
        view = self._view_ref
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return
        if not interaction.guild or interaction.guild.id != view.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return

        try:
            message_interval = int(str(self.message_xp_interval.value).strip())
            levelup_cooldown = int(str(self.levelup_cooldown.value).strip())
        except ValueError:
            await self.bot._reply(interaction, "Bitte gueltige Zahlen eingeben.", ephemeral=True)
            return

        if message_interval < 1 or levelup_cooldown < 1:
            await self.bot._reply(interaction, "Werte muessen >= 1 sein.", ephemeral=True)
            return
        if message_interval > FEATURE_INTERVAL_MASK or levelup_cooldown > FEATURE_INTERVAL_MASK:
            await self.bot._reply(
                interaction,
                f"Werte muessen <= {FEATURE_INTERVAL_MASK} sein.",
                ephemeral=True,
            )
            return

        view.message_xp_interval_seconds = message_interval
        view.levelup_message_cooldown_seconds = levelup_cooldown
        await self.bot._reply(interaction, "Intervall-Einstellungen vorgemerkt.", ephemeral=True)


class SettingsToggleButton(discord.ui.Button):
    def __init__(
        self,
        bot: "RewriteDiscordBot",
        *,
        guild_id: int,
        attr_name: str,
        label_prefix: str,
        row: int = 3,
    ):
        super().__init__(style=discord.ButtonStyle.secondary, label=label_prefix, row=row)
        self.bot = bot
        self.guild_id = guild_id
        self.attr_name = attr_name
        self.label_prefix = label_prefix

    def _refresh_appearance(self, view: "SettingsView") -> None:
        value = bool(getattr(view, self.attr_name))
        self.style = discord.ButtonStyle.success if value else discord.ButtonStyle.danger
        self.label = f"{self.label_prefix}: {'AN' if value else 'AUS'}"

    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return

        view = self.view
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return

        current = bool(getattr(view, self.attr_name))
        setattr(view, self.attr_name, not current)
        self._refresh_appearance(view)
        await _safe_edit_message(interaction.message, view=view)
        await self.bot._reply(
            interaction,
            f"{self.label_prefix} ist jetzt {'aktiviert' if not current else 'deaktiviert'}.",
            ephemeral=True,
        )


class SettingsIntervalsButton(discord.ui.Button):
    def __init__(self, bot: "RewriteDiscordBot", *, guild_id: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Intervalle einstellen",
            custom_id=f"settings:{guild_id}:intervals",
            row=4,
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return
        view = self.view
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return
        try:
            await interaction.response.send_modal(SettingsIntervalsModal(self.bot, view))
        except Exception:
            await self.bot._reply(interaction, "Modal konnte nicht geoeffnet werden.", ephemeral=True)


class SettingsView(discord.ui.View):
    """Überarbeitetes Settings-Menü mit intuitiver Struktur."""
    
    def __init__(self, bot: "RewriteDiscordBot", *, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        settings = bot.repo.ensure_settings(guild_id)
        feature_settings = bot._get_guild_feature_settings(guild_id)
        
        # Channel Settings
        self.planner_channel_id: int | None = settings.planner_channel_id
        self.participants_channel_id: int | None = settings.participants_channel_id
        self.raidlist_channel_id: int | None = settings.raidlist_channel_id
        
        # Feature toggles
        self.leveling_enabled: bool = feature_settings.leveling_enabled
        self.levelup_messages_enabled: bool = feature_settings.levelup_messages_enabled
        self.nanomon_reply_enabled: bool = feature_settings.nanomon_reply_enabled
        self.approved_reply_enabled: bool = feature_settings.approved_reply_enabled
        self.raid_reminder_enabled: bool = feature_settings.raid_reminder_enabled
        self.auto_reminder_enabled: bool = feature_settings.auto_reminder_enabled
        
        # Intervals
        self.message_xp_interval_seconds: int = feature_settings.message_xp_interval_seconds
        self.levelup_message_cooldown_seconds: int = feature_settings.levelup_message_cooldown_seconds

        # Channel Select Menu (Zeile 0)
        self.add_item(SettingsChannelSelect(bot, guild_id))
        
        # Feature Toggle Menu (Zeile 1)
        self.add_item(SettingsFeatureSelect(bot, guild_id))
        
        # Action Buttons (Zeile 2)
        self.add_item(SettingsIntervalsButton(bot, guild_id=guild_id))
        self.add_item(SettingsSaveButton(bot, guild_id))
        self.add_item(SettingsResetButton(bot, guild_id))

    def build_embed(self) -> discord.Embed:
        """Erstellt Übersichts-Embed mit aktuellen Einstellungen."""
        embed = discord.Embed(
            title="⚙️ Bot Einstellungen",
            description="Verwalte die Konfiguration des Raid Bots",
            color=discord.Color.blue()
        )
        
        # Channel Übersicht
        channels_text = (
            f"📋 **Umfragen:** {self._channel_mention(self.planner_channel_id)}\n"
            f"👥 **Teilnehmerlisten:** {self._channel_mention(self.participants_channel_id)}\n"
            f"📊 **Raidliste:** {self._channel_mention(self.raidlist_channel_id)}"
        )
        embed.add_field(name="📌 Channels", value=channels_text, inline=False)
        
        # Features Übersicht
        features_text = (
            f"📈 **Levelsystem:** {self._status_emoji(self.leveling_enabled)}\n"
            f"🎉 **Levelup Msg:** {self._status_emoji(self.levelup_messages_enabled)}\n"
            f"🤖 **Nanomon Reply:** {self._status_emoji(self.nanomon_reply_enabled)}\n"
            f"✅ **Approved Reply:** {self._status_emoji(self.approved_reply_enabled)}\n"
            f"⏰ **Raid Reminder:** {self._status_emoji(self.raid_reminder_enabled)}\n"
            f"🔔 **Auto Reminder:** {self._status_emoji(self.auto_reminder_enabled)}"
        )
        embed.add_field(name="⚡ Features", value=features_text, inline=True)
        
        # Intervalle Übersicht
        intervals_text = (
            f"⏱️ **XP Interval:** {self.message_xp_interval_seconds}s\n"
            f"⏳ **Levelup Cooldown:** {self.levelup_message_cooldown_seconds}s"
        )
        embed.add_field(name="⏲️ Intervalle", value=intervals_text, inline=True)
        
        embed.set_footer(text="Ändere Einstellungen über die Menüs unten")
        return embed
    
    def _channel_mention(self, channel_id: int | None) -> str:
        """Formatiert Channel-ID für Embed."""
        if channel_id:
            return f"<#{channel_id}>"
        return "❌ *Nicht gesetzt*"
    
    def _status_emoji(self, enabled: bool) -> str:
        """Gibt Status-Emoji zurück."""
        return "🟢 AN" if enabled else "🔴 AUS"


class SettingsChannelSelect(discord.ui.Select):
    """Auswahl welcher Channel-Typ konfiguriert werden soll."""
    
    def __init__(self, bot: "RewriteDiscordBot", guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        
        options = [
            discord.SelectOption(
                label="Umfragen Channel",
                value="planner",
                description="Channel für Raid-Umfragen",
                emoji="📋"
            ),
            discord.SelectOption(
                label="Teilnehmerlisten Channel", 
                value="participants",
                description="Channel für automatische Teilnehmerlisten",
                emoji="👥"
            ),
            discord.SelectOption(
                label="Raidlist Channel",
                value="raidlist", 
                description="Channel für die Raid-Übersicht",
                emoji="📊"
            )
        ]
        
        super().__init__(
            placeholder="📌 Channel konfigurieren...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id=f"settings:{guild_id}:channel_type",
            row=0
        )
    
    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungültiger Guild-Kontext.", ephemeral=True)
            return
        
        channel_type = self.values[0] if self.values else None
        if not channel_type:
            return
        
        view = self.view
        if not isinstance(view, SettingsView):
            return
        
        # Zeige Channel-Select für den gewählten Typ
        channel_select = discord.ui.ChannelSelect(
            placeholder=f"{channel_type.capitalize()} Channel wählen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{self.guild_id}:{channel_type}_channel"
        )
        
        temp_view = discord.ui.View(timeout=60)
        temp_view.add_item(channel_select)
        
        async def on_channel_select(interaction2: discord.Interaction):
            selected = interaction2.data.get("values", []) if interaction2.data else []
            channel_id = int(selected[0]) if selected else None
            
            if channel_type == "planner":
                view.planner_channel_id = channel_id
                msg = "📋 Umfragen Channel gesetzt"
            elif channel_type == "participants":
                view.participants_channel_id = channel_id
                msg = "👥 Teilnehmerlisten Channel gesetzt"
            elif channel_type == "raidlist":
                view.raidlist_channel_id = channel_id
                msg = "📊 Raidlist Channel gesetzt"
            
            await interaction2.response.edit_message(
                embed=view.build_embed(),
                view=view
            )
            await interaction2.followup.send(msg, ephemeral=True)
        
        channel_select.callback = on_channel_select
        
        await interaction.response.send_message(
            f"Wähle den Channel für **{channel_type}**:",
            view=temp_view,
            ephemeral=True
        )


class SettingsFeatureSelect(discord.ui.Select):
    """Multi-Select für Features mit intuitiver Darstellung."""
    
    def __init__(self, bot: "RewriteDiscordBot", guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        
        options = [
            discord.SelectOption(
                label="Levelsystem",
                value="leveling",
                description="XP und Level-System aktivieren",
                emoji="📈"
            ),
            discord.SelectOption(
                label="Levelup Nachrichten",
                value="levelup",
                description="Gratulations-Nachrichten bei Level-Up",
                emoji="🎉"
            ),
            discord.SelectOption(
                label="Nanomon Reply",
                value="nanomon",
                description="Reagiere auf 'nanomon' Keyword",
                emoji="🤖"
            ),
            discord.SelectOption(
                label="Approved Reply",
                value="approved",
                description="Reagiere auf 'approved' Keyword",
                emoji="✅"
            ),
            discord.SelectOption(
                label="Raid Reminder",
                value="raid_reminder",
                description="Erinnerungen 10 Minuten vor Raid",
                emoji="⏰"
            ),
            discord.SelectOption(
                label="Auto Reminder",
                value="auto_reminder",
                description="Erinnerung bei schwacher Beteiligung (2h vorher)",
                emoji="🔔"
            )
        ]
        
        super().__init__(
            placeholder="⚡ Features aktivieren/deaktivieren...",
            options=options,
            min_values=0,
            max_values=len(options),
            custom_id=f"settings:{guild_id}:features",
            row=1
        )
    
    async def callback(self, interaction):
        view = self.view
        if not isinstance(view, SettingsView):
            return
        
        selected = set(self.values) if self.values else set()
        
        # Setze alle Features basierend auf Auswahl
        view.leveling_enabled = "leveling" in selected
        view.levelup_messages_enabled = "levelup" in selected
        view.nanomon_reply_enabled = "nanomon" in selected
        view.approved_reply_enabled = "approved" in selected
        view.raid_reminder_enabled = "raid_reminder" in selected
        view.auto_reminder_enabled = "auto_reminder" in selected
        
        # Update Embed
        await interaction.response.edit_message(
            embed=view.build_embed(),
            view=view
        )
        
        # Zähle Änderungen
        changed = len(selected)
        await interaction.followup.send(
            f"✅ {changed} Features aktualisiert",
            ephemeral=True
        )


class SettingsResetButton(discord.ui.Button):
    """Button zum Zurücksetzen auf Standardwerte."""
    
    def __init__(self, bot: "RewriteDiscordBot", guild_id: int):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Zurücksetzen",
            emoji="🔄",
            custom_id=f"settings:{guild_id}:reset",
            row=2
        )
        self.bot = bot
        self.guild_id = guild_id
    
    async def callback(self, interaction):
        view = self.view
        if not isinstance(view, SettingsView):
            return
        
        # Reset auf Defaults
        view.planner_channel_id = None
        view.participants_channel_id = None
        view.raidlist_channel_id = None
        view.leveling_enabled = True
        view.levelup_messages_enabled = True
        view.nanomon_reply_enabled = True
        view.approved_reply_enabled = True
        view.raid_reminder_enabled = False
        view.auto_reminder_enabled = False
        view.message_xp_interval_seconds = 15
        view.levelup_message_cooldown_seconds = 20
        
        await interaction.response.edit_message(
            embed=view.build_embed(),
            view=view
        )
        await interaction.followup.send(
            "🔄 Alle Einstellungen auf Standard zurückgesetzt.\n"
            "Klicke 'Speichern' um die Änderungen zu übernehmen.",
            ephemeral=True
        )

class SettingsSaveButton(discord.ui.Button):
    def __init__(self, bot: "RewriteDiscordBot", guild_id: int):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="Speichern",
            custom_id=f"settings:{guild_id}:save",
            row=4,
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return

        view = self.view
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)
        async with self.bot._state_lock:
            row = save_channel_settings(
                self.bot.repo,
                guild_id=interaction.guild.id,
                guild_name=interaction.guild.name,
                planner_channel_id=view.planner_channel_id,
                participants_channel_id=view.participants_channel_id,
                raidlist_channel_id=view.raidlist_channel_id,
            )
            feature_row = self.bot._set_guild_feature_settings(
                interaction.guild.id,
                GuildFeatureSettings(
                    leveling_enabled=view.leveling_enabled,
                    levelup_messages_enabled=view.levelup_messages_enabled,
                    nanomon_reply_enabled=view.nanomon_reply_enabled,
                    approved_reply_enabled=view.approved_reply_enabled,
                    raid_reminder_enabled=view.raid_reminder_enabled,
                    auto_reminder_enabled=view.auto_reminder_enabled,
                    message_xp_interval_seconds=view.message_xp_interval_seconds,
                    levelup_message_cooldown_seconds=view.levelup_message_cooldown_seconds,
                ),
            )
            await self.bot._refresh_raidlist_for_guild(interaction.guild.id, force=True)
            persisted = await self.bot._persist(dirty_tables={"settings", "debug_cache"})

        if not persisted:
            await _safe_followup(interaction, "Settings konnten nicht gespeichert werden.", ephemeral=True)
            return
        await _safe_followup(
            interaction,
            (
                "Settings gespeichert:\n"
                f"Umfragen: `{row.planner_channel_id}`\n"
                f"Teilnehmerlisten: `{row.participants_channel_id}`\n"
                f"Raidlist: `{row.raidlist_channel_id}`\n"
                f"Levelsystem: `{_on_off(feature_row.leveling_enabled)}`\n"
                f"Levelup Msg: `{_on_off(feature_row.levelup_messages_enabled)}`\n"
                f"Nanomon Reply: `{_on_off(feature_row.nanomon_reply_enabled)}`\n"
                f"Approved Reply: `{_on_off(feature_row.approved_reply_enabled)}`\n"
                f"Raid Reminder: `{_on_off(feature_row.raid_reminder_enabled)}`\n"
                f"Auto Reminder: `{_on_off(feature_row.auto_reminder_enabled)}`\n"
                f"Message XP Intervall: `{feature_row.message_xp_interval_seconds}`\n"
                f"Levelup Cooldown: `{feature_row.levelup_message_cooldown_seconds}`"
            ),
            ephemeral=True,
        )


class FinishButton(discord.ui.Button):
    def __init__(self, bot: "RewriteDiscordBot", raid_id: int):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Raid beenden",
            custom_id=f"raid:{raid_id}:finish",
        )
        self.bot = bot
        self.raid_id = raid_id

    async def callback(self, interaction):
        await self.bot._defer(interaction, ephemeral=True)
        await self.bot._finish_raid_interaction(interaction, raid_id=self.raid_id, deferred=True)


class RaidVoteView(discord.ui.View):
    def __init__(self, bot: "RewriteDiscordBot", raid_id: int, days: list[str], times: list[str]):
        super().__init__(timeout=None)
        self.bot = bot
        self.raid_id = raid_id

        day_values = days[:25]
        time_values = times[:25]

        if day_values:
            day_select = discord.ui.Select(
                placeholder="Tage waehlen/abwaehlen...",
                min_values=1,
                max_values=min(25, max(1, len(day_values))),
                options=[discord.SelectOption(label=value, value=value) for value in day_values],
                custom_id=f"raid:{raid_id}:day",
            )
            day_select.callback = self.on_day_select
            self.add_item(day_select)

        if time_values:
            time_select = discord.ui.Select(
                placeholder="Uhrzeiten waehlen/abwaehlen...",
                min_values=1,
                max_values=min(25, max(1, len(time_values))),
                options=[discord.SelectOption(label=value, value=value) for value in time_values],
                custom_id=f"raid:{raid_id}:time",
            )
            time_select.callback = self.on_time_select
            self.add_item(time_select)

        self.add_item(FinishButton(bot, raid_id))

    async def _vote(self, interaction, *, kind: str) -> None:
        if not interaction.guild:
            await self.bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)
        values = [str(value) for value in ((interaction.data or {}).get("values") or [])]
        if not values:
            await _safe_followup(interaction, "Keine Werte ausgewaehlt.", ephemeral=True)
            return

        applied = 0
        raid_id_for_refresh: int | None = None
        async with self.bot._state_lock:
            raid = self.bot.repo.get_raid(self.raid_id)
            if raid is None or raid.status != "open":
                await _safe_followup(interaction, "Raid ist nicht mehr aktiv.", ephemeral=True)
                return

            labels = self.bot.repo.list_raid_options(raid.id)[0 if kind == "day" else 1]
            lookup = {label.lower(): label for label in labels}
            applied = 0
            for raw in values:
                selected = lookup.get(raw.strip().lower())
                if selected is None:
                    continue
                toggle_vote(
                    self.bot.repo,
                    raid_id=raid.id,
                    kind=kind,
                    option_label=selected,
                    user_id=interaction.user.id,
                )
                applied += 1

            if applied == 0:
                await _safe_followup(interaction, "Keine gueltige Option erkannt.", ephemeral=True)
                return

            raid_id_for_refresh = int(raid.id)

        if raid_id_for_refresh is not None:
            await self.bot._sync_vote_ui_after_change(raid_id_for_refresh)

        async with self.bot._state_lock:
            persisted = await self.bot._persist(
                dirty_tables={"raid_votes", "raid_posted_slots", "raids", "debug_cache"}
            )

        voter = _member_name(interaction.user) or str(interaction.user.id)
        if not persisted:
            await _safe_followup(interaction, "Stimme gesetzt, aber DB-Speicherung fehlgeschlagen.", ephemeral=True)
            return
        await _safe_followup(interaction, f"Stimme aktualisiert fuer **{voter}**.", ephemeral=True)

    async def on_day_select(self, interaction):
        await self._vote(interaction, kind="day")

    async def on_time_select(self, interaction):
        await self._vote(interaction, kind="time")

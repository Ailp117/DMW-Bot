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
    ):
        super().__init__(style=discord.ButtonStyle.secondary, label=label_prefix, row=3)
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
    def __init__(self, bot: "RewriteDiscordBot", *, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        settings = bot.repo.ensure_settings(guild_id)
        feature_settings = bot._get_guild_feature_settings(guild_id)
        self.planner_channel_id: int | None = settings.planner_channel_id
        self.participants_channel_id: int | None = settings.participants_channel_id
        self.raidlist_channel_id: int | None = settings.raidlist_channel_id
        self.leveling_enabled: bool = feature_settings.leveling_enabled
        self.levelup_messages_enabled: bool = feature_settings.levelup_messages_enabled
        self.nanomon_reply_enabled: bool = feature_settings.nanomon_reply_enabled
        self.approved_reply_enabled: bool = feature_settings.approved_reply_enabled
        self.raid_reminder_enabled: bool = feature_settings.raid_reminder_enabled
        self.message_xp_interval_seconds: int = feature_settings.message_xp_interval_seconds
        self.levelup_message_cooldown_seconds: int = feature_settings.levelup_message_cooldown_seconds

        planner_select = discord.ui.ChannelSelect(
            placeholder="Umfragen Channel waehlen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{guild_id}:planner",
            row=0,
        )
        participants_select = discord.ui.ChannelSelect(
            placeholder="Raid Teilnehmerlisten Channel waehlen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{guild_id}:participants",
            row=1,
        )
        raidlist_select = discord.ui.ChannelSelect(
            placeholder="Raidlist Channel waehlen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{guild_id}:raidlist",
            row=2,
        )

        planner_select.callback = self._on_planner_select
        participants_select.callback = self._on_participants_select
        raidlist_select.callback = self._on_raidlist_select

        self.add_item(planner_select)
        self.add_item(participants_select)
        self.add_item(raidlist_select)

        toggle_items = [
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="leveling_enabled",
                label_prefix="Levelsystem",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="levelup_messages_enabled",
                label_prefix="Levelup Msg",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="nanomon_reply_enabled",
                label_prefix="Nanomon Reply",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="approved_reply_enabled",
                label_prefix="Approved Reply",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="raid_reminder_enabled",
                label_prefix="Raid Reminder",
            ),
        ]
        for item in toggle_items:
            item._refresh_appearance(self)
            self.add_item(item)

        self.add_item(SettingsIntervalsButton(bot, guild_id=guild_id))
        self.add_item(SettingsSaveButton(bot, guild_id))

    async def _on_planner_select(self, interaction):
        selected = ((interaction.data or {}).get("values") or [])
        self.planner_channel_id = int(selected[0]) if selected else None
        await self.bot._defer(interaction, ephemeral=True)
        await _safe_followup(interaction, "Umfragen Channel vorgemerkt.", ephemeral=True)

    async def _on_participants_select(self, interaction):
        selected = ((interaction.data or {}).get("values") or [])
        self.participants_channel_id = int(selected[0]) if selected else None
        await self.bot._defer(interaction, ephemeral=True)
        await _safe_followup(interaction, "Raid Teilnehmerlisten Channel vorgemerkt.", ephemeral=True)

    async def _on_raidlist_select(self, interaction):
        selected = ((interaction.data or {}).get("values") or [])
        self.raidlist_channel_id = int(selected[0]) if selected else None
        await self.bot._defer(interaction, ephemeral=True)
        await _safe_followup(interaction, "Raidlist Channel vorgemerkt.", ephemeral=True)

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

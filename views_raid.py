# views_raid.py
from __future__ import annotations

import discord
from typing import Optional
from discord.ui import View, Select, Button

from db import get_session
from models import Raid
from helpers import (
    get_raid,
    get_options,
    build_summary,
    build_embed_for_raid,
    toggle_vote,
    get_guild_settings,
    get_users_for_day,
    get_users_for_time,
    get_posted_slot_row,
    upsert_posted_slot_message,
    get_all_posted_slots,
    delete_raid_completely,
    short_list,
)
from roles import (
    ensure_temp_role_for_raid,
    compute_desired_role_users_for_raid,
    sync_role_membership,
    cleanup_temp_role,
)
from raidlist import schedule_raidlist_refresh


def build_slot_text(
    raid: Raid,
    day_label: str,
    time_label: str,
    role: Optional[discord.Role],
    slot_user_ids: list[int],
) -> str:
    role_line = role.mention if role else "⚠️ (Rolle konnte nicht erstellt werden – fehlende Rechte?)"
    mentions = [f"<@{uid}>" for uid in slot_user_ids]
    return (
        f"✅ **Teilnehmerliste – {raid.dungeon}**\n"
        f"🆔 **Raid:** {raid.id}\n"
        f"📅 **Tag:** {day_label}\n"
        f"🕒 **Uhrzeit:** {time_label}\n"
        f"👥 Teilnehmer (**{len(slot_user_ids)} / {raid.min_players}**)\n"
        f"{role_line}\n\n"
        f"**Liste:**\n{short_list(mentions)}"
    )


async def delete_participant_list_messages_for_raid(client: discord.Client, session, raid_id: int):
    rows = await get_all_posted_slots(session, raid_id)
    for r in rows:
        if not r.channel_id or not r.message_id:
            continue
        ch = client.get_channel(r.channel_id)
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            continue
        try:
            msg = await ch.fetch_message(r.message_id)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


class RaidCreateModal(discord.ui.Modal, title="Raid Optionen"):
    days = discord.ui.TextInput(
        label="Tage (Komma/Zeilen getrennt)",
        placeholder="z.B. Mo, Di, Mi",
        required=True,
        max_length=400,
    )
    times = discord.ui.TextInput(
        label="Uhrzeiten (Komma/Zeilen getrennt)",
        placeholder="z.B. 19:00, 20:30",
        required=True,
        max_length=400,
    )
    min_players = discord.ui.TextInput(
        label="Benötigte Spieler pro Slot (Zahl)",
        placeholder="z.B. 4",
        required=True,
        max_length=3,
    )

    def __init__(self, dungeon_name: str):
        super().__init__()
        self.dungeon_name = dungeon_name
        self.result: Optional[tuple[str, str, int]] = None

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mp = int(str(self.min_players.value).strip())
            if mp < 0:
                raise ValueError()
        except ValueError:
            return await interaction.response.send_message(
                "❌ Min. Spieler muss eine Zahl >= 0 sein.",
                ephemeral=True,
            )

        self.result = (str(self.days.value), str(self.times.value), mp)
        await interaction.response.defer(ephemeral=True)


class RaidFinishButton(Button):
    def __init__(self, raid_id: int):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Raid abgeschlossen",
            custom_id=f"raid:{raid_id}:finish",
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        if not interaction.response.is_done():
            await interaction.response.defer()

        async with await get_session() as session:
            raid = await get_raid(session, self.raid_id)
            if not raid:
                return await interaction.followup.send(
                    "Raid nicht gefunden (evtl. bereits gelöscht).",
                    ephemeral=True,
                )

            if raid.creator_id != interaction.user.id:
                return await interaction.followup.send(
                    "Nur der Raid-Ersteller kann das abschließen.",
                    ephemeral=True,
                )

            dungeon_name = raid.dungeon

            await delete_participant_list_messages_for_raid(interaction.client, session, self.raid_id)
            await cleanup_temp_role(session, interaction.guild, raid)
            await delete_raid_completely(session, self.raid_id)

        # debounced raidlist update after finishing raid
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

        if self.view:
            for item in self.view.children:
                item.disabled = True

        embed = discord.Embed(
            title="DMW Raid Planer",
            description=(
                "✅ Raid abgeschlossen.\n"
                "Teilnehmerlisten wurden gelöscht.\n"
                "Alle Raid-Daten wurden gelöscht.\n"
                f"**Dungeon:** {dungeon_name}"
            ),
        )
        await interaction.edit_original_response(embed=embed, view=self.view)


class RaidVoteView(View):
    def __init__(self, raid_id: int, days: list[str], times: list[str]):
        super().__init__(timeout=None)
        self.raid_id = raid_id

        self.day_select = Select(
            placeholder="Tage wählen/abwählen…",
            min_values=1,
            max_values=min(25, max(1, len(days))),
            options=[discord.SelectOption(label=d, value=d) for d in days[:25]],
            custom_id=f"raid:{raid_id}:day",
        )
        self.time_select = Select(
            placeholder="Uhrzeiten wählen/abwählen…",
            min_values=1,
            max_values=min(25, max(1, len(times))),
            options=[discord.SelectOption(label=t, value=t) for t in times[:25]],
            custom_id=f"raid:{raid_id}:time",
        )

        self.day_select.callback = self.on_day_select
        self.time_select.callback = self.on_time_select

        self.add_item(self.day_select)
        self.add_item(self.time_select)
        self.add_item(RaidFinishButton(raid_id))

    async def _refresh_message(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        if not interaction.response.is_done():
            await interaction.response.defer()

        async with await get_session() as session:
            raid = await get_raid(session, self.raid_id)
            if not raid:
                for item in self.children:
                    item.disabled = True
                embed = discord.Embed(
                    title="DMW Raid Planer",
                    description="✅ Raid ist nicht mehr aktiv (Daten gelöscht).",
                )
                await interaction.edit_original_response(embed=embed, view=self)
                return

            summary = await build_summary(session, self.raid_id)
            embed = await build_embed_for_raid(raid, summary)

            settings = await get_guild_settings(session, raid.guild_id)
            participants_ch_id = settings.participants_channel_id if settings else None

            role: Optional[discord.Role] = None
            if raid.min_players > 0:
                role = await ensure_temp_role_for_raid(session, interaction.guild, raid)
                if role:
                    desired = await compute_desired_role_users_for_raid(session, self.raid_id, raid.min_players)
                    await sync_role_membership(interaction.guild, role, desired)

            # Post / update participant slot messages
            if raid.status == "open" and raid.min_players > 0 and participants_ch_id:
                ch = interaction.client.get_channel(participants_ch_id)
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    days, times = await get_options(session, self.raid_id)

                    for d in days:
                        day_users = await get_users_for_day(session, self.raid_id, d)
                        if not day_users:
                            continue
                        for t in times:
                            time_users = await get_users_for_time(session, self.raid_id, t)
                            if not time_users:
                                continue

                            slot_users = sorted(set(day_users.intersection(time_users)))
                            if len(slot_users) < raid.min_players:
                                continue

                            text_msg = build_slot_text(raid, d, t, role, slot_users)
                            row = await get_posted_slot_row(session, self.raid_id, d, t)

                            if not row or not row.message_id:
                                msg = await ch.send(
                                    text_msg,
                                    allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                                )
                                await upsert_posted_slot_message(session, self.raid_id, d, t, ch.id, msg.id)
                            else:
                                try:
                                    msg = await ch.fetch_message(row.message_id)
                                    await msg.edit(
                                        content=text_msg,
                                        allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                                    )
                                except (discord.NotFound, discord.Forbidden):
                                    msg = await ch.send(
                                        text_msg,
                                        allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                                    )
                                    await upsert_posted_slot_message(session, self.raid_id, d, t, ch.id, msg.id)

        await interaction.edit_original_response(embed=embed, view=self)

        # debounced raidlist update after refresh (vote changes + slot changes)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

    async def on_day_select(self, interaction: discord.Interaction):
        values = interaction.data.get("values", []) if interaction.data else []
        async with await get_session() as session:
            for v in values:
                await toggle_vote(session, self.raid_id, "day", v, interaction.user.id)
        await self._refresh_message(interaction)

    async def on_time_select(self, interaction: discord.Interaction):
        values = interaction.data.get("values", []) if interaction.data else []
        async with await get_session() as session:
            for v in values:
                await toggle_vote(session, self.raid_id, "time", v, interaction.user.id)
        await self._refresh_message(interaction)

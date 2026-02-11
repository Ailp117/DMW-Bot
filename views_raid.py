import discord
from typing import Optional
from discord.ui import View, Select, Button

from helpers import (
    get_raid, get_options, vote_counts, toggle_vote,
    get_slot_user_ids, get_posted_slot, upsert_posted_slot,
    delete_raid_completely, short_list, set_raid_message_id
)
from helpers import get_or_create_settings
from roles import ensure_temp_role, compute_role_members_for_raid, sync_role_membership, cleanup_temp_role
from raidlist import schedule_raidlist_refresh


class RaidCreateModal(discord.ui.Modal, title="Raid erstellen"):
    days = discord.ui.TextInput(label="Tage (Komma/Zeilen)", required=True, max_length=400)
    times = discord.ui.TextInput(label="Uhrzeiten (Komma/Zeilen)", required=True, max_length=400)
    min_players = discord.ui.TextInput(label="Min Spieler pro Slot (0 = aus)", required=True, max_length=3)

    def __init__(self):
        super().__init__()
        self.result: tuple[list[str], list[str], int] | None = None

    async def on_submit(self, interaction: discord.Interaction):
        from helpers import normalize_list
        try:
            mp = int(str(self.min_players.value).strip())
            if mp < 0:
                raise ValueError()
        except ValueError:
            return await interaction.response.send_message("❌ Min Spieler muss Zahl >= 0 sein.", ephemeral=True)

        d = normalize_list(str(self.days.value))
        t = normalize_list(str(self.times.value))
        if not d or not t:
            return await interaction.response.send_message("❌ Bitte mind. 1 Tag und 1 Uhrzeit.", ephemeral=True)

        self.result = (d, t, mp)
        await interaction.response.defer(ephemeral=True)


def build_planner_embed(raid, counts: dict) -> discord.Embed:
    e = discord.Embed(title=f"🗓️ Raid Planer: {raid.dungeon}", description=f"Raid ID: `{raid.id}`")
    e.add_field(name="Min Spieler pro Slot", value=str(raid.min_players), inline=True)

    day_lines = []
    for k, v in sorted(counts["day"].items(), key=lambda x: (-x[1], x[0])):
        day_lines.append(f"• **{k}** — `{v}`")
    time_lines = []
    for k, v in sorted(counts["time"].items(), key=lambda x: (-x[1], x[0])):
        time_lines.append(f"• **{k}** — `{v}`")

    e.add_field(name="📅 Tage Votes", value="\n".join(day_lines) if day_lines else "—", inline=False)
    e.add_field(name="🕒 Uhrzeiten Votes", value="\n".join(time_lines) if time_lines else "—", inline=False)
    e.set_footer(text="Wähle Tag & Uhrzeit. Slots werden automatisch gepostet, wenn threshold erreicht ist.")
    return e


def slot_text(raid, day_label: str, time_label: str, role: Optional[discord.Role], user_ids: list[int]) -> str:
    mentions = [f"<@{u}>" for u in user_ids]
    role_line = role.mention if role else "⚠️ Rolle nicht verfügbar"
    return (
        f"✅ **Teilnehmerliste – {raid.dungeon}**\n"
        f"🆔 Raid: `{raid.id}`\n"
        f"📅 Tag: **{day_label}**\n"
        f"🕒 Zeit: **{time_label}**\n"
        f"👥 Teilnehmer: **{len(user_ids)} / {raid.min_players}**\n"
        f"{role_line}\n\n"
        f"{short_list(mentions)}"
    )


class FinishButton(Button):
    def __init__(self, raid_id: int):
        super().__init__(style=discord.ButtonStyle.danger, label="Raid beenden", custom_id=f"raid:{raid_id}:finish")
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        raid = await get_raid(self.raid_id)
        if not raid:
            return await interaction.followup.send("Raid existiert nicht mehr.", ephemeral=True)

        if interaction.user.id != raid.creator_id:
            return await interaction.followup.send("Nur der Ersteller kann beenden.", ephemeral=True)

        # cleanup role + delete raid
        await cleanup_temp_role(interaction.guild, raid.dungeon)
        await delete_raid_completely(self.raid_id)

        for item in self.view.children:
            item.disabled = True

        await interaction.edit_original_response(embed=discord.Embed(title="✅ Raid beendet"), view=self.view)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)


class RaidVoteView(View):
    def __init__(self, raid_id: int, days: list[str], times: list[str]):
        super().__init__(timeout=None)
        self.raid_id = raid_id

        self.day_select = Select(
            placeholder="Tage wählen…",
            min_values=1,
            max_values=min(25, max(1, len(days))),
            options=[discord.SelectOption(label=d, value=d) for d in days[:25]],
            custom_id=f"raid:{raid_id}:day",
        )
        self.time_select = Select(
            placeholder="Uhrzeiten wählen…",
            min_values=1,
            max_values=min(25, max(1, len(times))),
            options=[discord.SelectOption(label=t, value=t) for t in times[:25]],
            custom_id=f"raid:{raid_id}:time",
        )

        self.day_select.callback = self.on_day_select
        self.time_select.callback = self.on_time_select

        self.add_item(self.day_select)
        self.add_item(self.time_select)
        self.add_item(FinishButton(raid_id))

    async def _refresh(self, interaction: discord.Interaction):
        raid = await get_raid(self.raid_id)
        if not raid:
            for i in self.children:
                i.disabled = True
            await interaction.edit_original_response(embed=discord.Embed(title="Raid nicht mehr aktiv."), view=self)
            return

        counts = await vote_counts(self.raid_id)
        embed = build_planner_embed(raid, counts)

        # role sync (minimal)
        role = None
        if raid.min_players > 0:
            role = await ensure_temp_role(interaction.guild, raid.dungeon)
            if role:
                desired = await compute_role_members_for_raid(self.raid_id, raid.min_players)
                await sync_role_membership(interaction.guild, role, desired)

        # slot messages
        if raid.min_players > 0:
            s = await get_or_create_settings(raid.guild_id)
            if s.participants_channel_id:
                ch = interaction.client.get_channel(int(s.participants_channel_id))
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    days, times = await get_options(self.raid_id)
                    for d in days:
                        for t in times:
                            users = await get_slot_user_ids(self.raid_id, d, t)
                            if len(users) < raid.min_players:
                                continue

                            txt = slot_text(raid, d, t, role, users)
                            row = await get_posted_slot(self.raid_id, d, t)
                            if not row:
                                msg = await ch.send(txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                                await upsert_posted_slot(self.raid_id, d, t, ch.id, msg.id)
                            else:
                                try:
                                    msg = await ch.fetch_message(int(row.message_id))
                                    await msg.edit(content=txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                                except (discord.NotFound, discord.Forbidden):
                                    msg = await ch.send(txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                                    await upsert_posted_slot(self.raid_id, d, t, ch.id, msg.id)

        await interaction.edit_original_response(embed=embed, view=self)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

    async def on_day_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for v in interaction.data.get("values", []):
            await toggle_vote(self.raid_id, "day", v, interaction.user.id)
        await self._refresh(interaction)

    async def on_time_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for v in interaction.data.get("values", []):
            await toggle_vote(self.raid_id, "time", v, interaction.user.id)
        await self._refresh(interaction)

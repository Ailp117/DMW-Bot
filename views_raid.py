import discord
from discord.ui import View, Select, Button
from sqlalchemy import select

from db import session_scope
from models import Raid, RaidPostedSlot
from helpers import (
    normalize_list, get_settings, create_raid, get_raid, get_options,
    toggle_vote, vote_counts, slot_users, get_posted_slot, upsert_posted_slot,
    delete_raid_cascade, short_list
)
from roles import ensure_temp_role, cleanup_temp_role
from raidlist import schedule_raidlist_refresh


def planner_embed(raid: Raid, counts: dict[str, dict[str, int]]) -> discord.Embed:
    e = discord.Embed(title=f"🗓️ Raid Planer: {raid.dungeon}", description=f"Raid ID: `{raid.id}`")
    e.add_field(name="Min Spieler pro Slot", value=str(raid.min_players), inline=True)

    day_lines = [f"• **{k}** — `{v}`" for k, v in sorted(counts["day"].items(), key=lambda x: (-x[1], x[0]))]
    time_lines = [f"• **{k}** — `{v}`" for k, v in sorted(counts["time"].items(), key=lambda x: (-x[1], x[0]))]

    e.add_field(name="📅 Tage Votes", value="\n".join(day_lines) if day_lines else "—", inline=False)
    e.add_field(name="🕒 Uhrzeiten Votes", value="\n".join(time_lines) if time_lines else "—", inline=False)
    e.set_footer(text="Wähle Tag & Uhrzeit. Slots werden gepostet, wenn threshold erreicht ist.")
    return e


def slot_text(raid: Raid, day_label: str, time_label: str, role: discord.Role | None, user_ids: list[int]) -> str:
    mentions = [f"<@{u}>" for u in user_ids]
    return (
        f"✅ **Teilnehmerliste – {raid.dungeon}**\n"
        f"🆔 Raid: `{raid.id}`\n"
        f"📅 Tag: **{day_label}**\n"
        f"🕒 Zeit: **{time_label}**\n"
        f"👥 Teilnehmer: **{len(user_ids)} / {raid.min_players}**\n"
        f"{role.mention if role else '⚠️ Rolle nicht verfügbar'}\n\n"
        f"{short_list(mentions)}"
    )


class RaidCreateModal(discord.ui.Modal, title="Raid erstellen"):
    days = discord.ui.TextInput(label="Tage (Komma/Zeilen)", required=True, max_length=400)
    times = discord.ui.TextInput(label="Uhrzeiten (Komma/Zeilen)", required=True, max_length=400)
    min_players = discord.ui.TextInput(label="Min Spieler pro Slot (0=aus)", required=True, max_length=3)

    def __init__(self, dungeon_name: str):
        super().__init__()
        self.dungeon_name = dungeon_name

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        # ✅ acknowledge modal submit quickly
        await interaction.response.defer(ephemeral=True)

        # parse inputs
        try:
            mp = int(str(self.min_players.value).strip())
            if mp < 0:
                raise ValueError()
        except ValueError:
            return await interaction.followup.send("❌ Min Spieler muss Zahl >= 0 sein.", ephemeral=True)

        days = normalize_list(str(self.days.value))
        times = normalize_list(str(self.times.value))
        if not days or not times:
            return await interaction.followup.send("❌ Bitte mind. 1 Tag und 1 Uhrzeit angeben.", ephemeral=True)

        # create raid + post planner message
        async with session_scope() as session:
            s = await get_settings(session, interaction.guild.id)
            if not s.planner_channel_id or not s.participants_channel_id:
                return await interaction.followup.send(
                    "❌ Settings fehlen. Bitte `/settings` konfigurieren.",
                    ephemeral=True,
                )

            raid = await create_raid(
                session=session,
                guild_id=interaction.guild.id,
                planner_channel_id=int(s.planner_channel_id),
                creator_id=interaction.user.id,
                dungeon=self.dungeon_name,
                days=days,
                times=times,
                min_players=mp,
            )

            counts = {"day": {}, "time": {}}
            embed = planner_embed(raid, counts)
            view = RaidVoteView(raid.id, days, times)

            # send message in planner channel
            ch = interaction.client.get_channel(int(s.planner_channel_id))
            if ch is None:
                try:
                    ch = await interaction.client.fetch_channel(int(s.planner_channel_id))
                except (discord.NotFound, discord.Forbidden):
                    return await interaction.followup.send("❌ Planner Channel nicht erreichbar.", ephemeral=True)

            if not isinstance(ch, (discord.TextChannel, discord.Thread)):
                return await interaction.followup.send("❌ Planner Channel ist kein Text-Channel.", ephemeral=True)

            msg = await ch.send(embed=embed, view=view)
            raid.message_id = msg.id  # ✅ store for raidlist jump url + persistence

        # refresh raidlist (debounced)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

        await interaction.followup.send(
            f"✅ Raid erstellt: **{self.dungeon_name}** (ID `{raid.id}`)\n"
            f"➡️ Im Planner Channel gepostet: {msg.jump_url}",
            ephemeral=True,
        )


async def cleanup_posted_slot_messages(session, interaction: discord.Interaction, raid_id: int) -> None:
    rows = (await session.execute(
        select(RaidPostedSlot).where(RaidPostedSlot.raid_id == raid_id)
    )).scalars().all()

    for row in rows:
        if row.channel_id is None or row.message_id is None:
            continue

        ch = interaction.client.get_channel(int(row.channel_id))
        if ch is None:
            try:
                ch = await interaction.client.fetch_channel(int(row.channel_id))
            except (discord.NotFound, discord.Forbidden):
                continue

        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            continue

        try:
            msg = await ch.fetch_message(int(row.message_id))
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            continue



class FinishButton(Button):
    def __init__(self, raid_id: int):
        super().__init__(style=discord.ButtonStyle.danger, label="Raid beenden", custom_id=f"raid:{raid_id}:finish")
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with session_scope() as session:
            raid = await get_raid(session, self.raid_id)
            if not raid:
                return await interaction.followup.send("Raid existiert nicht mehr.", ephemeral=True)

            if interaction.user.id != raid.creator_id:
                return await interaction.followup.send("Nur der Ersteller kann beenden.", ephemeral=True)

            # cleanup participant list messages + role + delete raid (cascade)
            await cleanup_posted_slot_messages(session, interaction, raid.id)
            await cleanup_temp_role(session, interaction.guild, raid)
            await delete_raid_cascade(session, raid.id)

        # disable view
        if self.view:
            for item in self.view.children:
                item.disabled = True

        await interaction.edit_original_response(embed=discord.Embed(title="✅ Raid beendet"), view=self.view)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)


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
        self.add_item(FinishButton(raid_id))

    async def refresh_view(self, interaction: discord.Interaction):
        async with session_scope() as session:
            raid = await get_raid(session, self.raid_id)
            if not raid:
                for c in self.children:
                    c.disabled = True
                return await interaction.edit_original_response(
                    embed=discord.Embed(title="Raid nicht mehr aktiv."),
                    view=self
                )

            counts = await vote_counts(session, self.raid_id)
            embed = planner_embed(raid, counts)

            s = await get_settings(session, raid.guild_id)

            # role
            role = None
            if raid.min_players > 0:
                role = await ensure_temp_role(session, interaction.guild, raid)

            # slots
            if raid.min_players > 0 and s.participants_channel_id:
                ch = interaction.client.get_channel(int(s.participants_channel_id))
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    days, times = await get_options(session, self.raid_id)
                    for d in days:
                        for t in times:
                            users = await slot_users(session, self.raid_id, d, t)
                            if len(users) < raid.min_players:
                                continue

                            txt = slot_text(raid, d, t, role, users)
                            row = await get_posted_slot(session, self.raid_id, d, t)

                            if not row:
                                msg = await ch.send(txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                                await upsert_posted_slot(session, self.raid_id, d, t, ch.id, msg.id)
                            else:
                                try:
                                    msg = await ch.fetch_message(int(row.message_id))
                                    await msg.edit(content=txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                                except (discord.NotFound, discord.Forbidden):
                                    msg = await ch.send(txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                                    await upsert_posted_slot(session, self.raid_id, d, t, ch.id, msg.id)

        await interaction.edit_original_response(embed=embed, view=self)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

    async def on_day_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        values = interaction.data.get("values", [])
        async with session_scope() as session:
            for v in values:
                await toggle_vote(session, self.raid_id, "day", v, interaction.user.id)
        await self.refresh_view(interaction)

    async def on_time_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        values = interaction.data.get("values", [])
        async with session_scope() as session:
            for v in values:
                await toggle_vote(session, self.raid_id, "time", v, interaction.user.id)
        await self.refresh_view(interaction)

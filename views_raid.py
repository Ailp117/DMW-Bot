import hashlib

import discord
from discord.ui import View, Select, Button
from sqlalchemy import select

from config import LOG_GUILD_ID, MEMBERLIST_DEBUG_CHANNEL_ID
from db import session_scope
from models import DebugMirrorCache, Raid, RaidPostedSlot
from helpers import (
    normalize_list, get_settings, create_raid, get_raid, get_options,
    toggle_vote, vote_counts, vote_user_sets, posted_slot_map, upsert_posted_slot,
    delete_raid_cascade, short_list
)
from roles import ensure_temp_role, cleanup_temp_role
from raidlist import schedule_raidlist_refresh




def _memberlist_threshold(min_players: int) -> int:
    return min_players if min_players > 0 else 1


def _memberlist_target_label(min_players: int) -> str:
    return str(min_players) if min_players > 0 else "1+"

def planner_embed(raid: Raid, counts: dict[str, dict[str, int]]) -> discord.Embed:
    e = discord.Embed(title=f"🗓️ Raid Planer: {raid.dungeon}", description=f"Raid ID: `{raid.display_id}`")
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
        f"🆔 Raid: `{raid.display_id}`\n"
        f"📅 Tag: **{day_label}**\n"
        f"🕒 Zeit: **{time_label}**\n"
        f"👥 Teilnehmer: **{len(user_ids)} / {_memberlist_target_label(raid.min_players)}**\n"
        f"{role.mention if role else ''}\n\n"
        f"{short_list(mentions)}"
    )


def _debug_cache_key_for_memberlist(guild_id: int, raid_id: int) -> str:
    return f"memberlist:{guild_id}:{raid_id}"


async def _load_debug_cache_entry(cache_key: str) -> DebugMirrorCache | None:
    async with session_scope() as session:
        return await session.get(DebugMirrorCache, cache_key)


async def _upsert_debug_cache_entry(
    cache_key: str,
    *,
    guild_id: int,
    raid_id: int,
    message_id: int,
    payload_hash: str,
) -> None:
    async with session_scope() as session:
        row = await session.get(DebugMirrorCache, cache_key)
        if row is None:
            row = DebugMirrorCache(
                cache_key=cache_key,
                kind="memberlist",
                guild_id=guild_id,
                raid_id=raid_id,
                message_id=message_id,
                payload_hash=payload_hash,
            )
            session.add(row)
            return

        row.message_id = message_id
        row.payload_hash = payload_hash


async def _mirror_memberlist_debug_for_guild(
    client: discord.Client,
    guild: discord.Guild,
    raid: Raid,
    slot_lines: list[str],
    *,
    force_refresh: bool = False,
) -> None:
    if guild.id == LOG_GUILD_ID or not MEMBERLIST_DEBUG_CHANNEL_ID:
        return

    channel = client.get_channel(MEMBERLIST_DEBUG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(MEMBERLIST_DEBUG_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden):
            return

    if not hasattr(channel, "send"):
        return

    if slot_lines:
        content = "\n".join(slot_lines)
    else:
        content = "Keine erfüllten Member-Slots für diesen Raid."

    header = (
        f"🧪 Memberlist Debug | Guild `{guild.id}` ({guild.name})\n"
        f"Raid `{raid.display_id}` (DB `{raid.id}`) | Dungeon **{raid.dungeon}**"
    )
    payload = f"{header}\n{content}"
    if len(payload) > 1900:
        payload = payload[:1897] + "..."

    cache_key = _debug_cache_key_for_memberlist(guild.id, raid.id)
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    cached = await _load_debug_cache_entry(cache_key)
    if (
        not force_refresh
        and cached is not None
        and cached.payload_hash == payload_hash
        and cached.message_id
    ):
        try:
            await channel.fetch_message(int(cached.message_id))
            return
        except (discord.NotFound, discord.Forbidden):
            pass

    if cached is not None and cached.message_id:
        try:
            msg = await channel.fetch_message(int(cached.message_id))
            await msg.edit(content=payload)
            await _upsert_debug_cache_entry(
                cache_key,
                guild_id=guild.id,
                raid_id=raid.id,
                message_id=msg.id,
                payload_hash=payload_hash,
            )
            return
        except (discord.NotFound, discord.Forbidden):
            pass

    msg = await channel.send(payload)
    await _upsert_debug_cache_entry(
        cache_key,
        guild_id=guild.id,
        raid_id=raid.id,
        message_id=msg.id,
        payload_hash=payload_hash,
    )


async def _mirror_memberlist_debug(interaction: discord.Interaction, raid: Raid, slot_lines: list[str]) -> None:
    if interaction.guild is None:
        return
    await _mirror_memberlist_debug_for_guild(interaction.client, interaction.guild, raid, slot_lines)


async def sync_memberlists_for_raid(
    client: discord.Client,
    guild: discord.Guild,
    raid_id: int,
    *,
    ensure_debug_mirror: bool = False,
) -> None:
    async with session_scope() as session:
        raid = await get_raid(session, raid_id)
        if not raid or raid.status != "open" or raid.guild_id != guild.id:
            return

        settings = await get_settings(session, raid.guild_id)
        if not settings.participants_channel_id:
            return

        role = await ensure_temp_role(session, guild, raid) if raid.min_players > 0 else None
        threshold = _memberlist_threshold(raid.min_players)

        target_channel = client.get_channel(int(settings.participants_channel_id))
        if target_channel is None:
            try:
                target_channel = await client.fetch_channel(int(settings.participants_channel_id))
            except (discord.NotFound, discord.Forbidden):
                return

        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            return

        days, times = await get_options(session, raid_id)
        day_users, time_users = await vote_user_sets(session, raid_id)
        slot_rows = await posted_slot_map(session, raid_id)

        debug_slot_lines: list[str] = []
        active_slot_keys: set[tuple[str, str]] = set()

        for d in days:
            for t in times:
                users = sorted(day_users.get(d, set()).intersection(time_users.get(t, set())))
                if len(users) < threshold:
                    continue

                active_slot_keys.add((d, t))
                txt = slot_text(raid, d, t, role, users)
                debug_slot_lines.append(f"• {d} {t}: {', '.join(f'<@{u}>' for u in users)}")
                row = slot_rows.get((d, t))

                if row:
                    try:
                        msg = await target_channel.fetch_message(int(row.message_id))
                        await msg.edit(content=txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                        continue
                    except (discord.NotFound, discord.Forbidden):
                        pass

                msg = await target_channel.send(txt, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                await upsert_posted_slot(session, raid_id, d, t, target_channel.id, msg.id)
                slot_rows[(d, t)] = RaidPostedSlot(
                    raid_id=raid_id,
                    day_label=d,
                    time_label=t,
                    channel_id=target_channel.id,
                    message_id=msg.id,
                )

        for key, row in list(slot_rows.items()):
            if key in active_slot_keys:
                continue

            cleanup_channel = client.get_channel(int(row.channel_id))
            if cleanup_channel is None:
                try:
                    cleanup_channel = await client.fetch_channel(int(row.channel_id))
                except (discord.NotFound, discord.Forbidden):
                    cleanup_channel = None

            if cleanup_channel is not None and hasattr(cleanup_channel, "fetch_message"):
                try:
                    old_msg = await cleanup_channel.fetch_message(int(row.message_id))
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            await session.delete(row)

        await _mirror_memberlist_debug_for_guild(
            client,
            guild,
            raid,
            debug_slot_lines,
            force_refresh=ensure_debug_mirror,
        )

class RaidCreateModal(discord.ui.Modal, title="Raid erstellen"):
    days = discord.ui.TextInput(label="Tage (Komma/Zeilen)", required=True, max_length=400)
    times = discord.ui.TextInput(label="Uhrzeiten (Komma/Zeilen)", required=True, max_length=400)
    min_players = discord.ui.TextInput(label="Min Spieler pro Slot (0=ab 1 Teilnehmer)", required=True, max_length=3)

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
            f"✅ Raid erstellt: **{self.dungeon_name}** (ID `{raid.display_id}`)\n"
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

            if s.participants_channel_id:
                await sync_memberlists_for_raid(interaction.client, interaction.guild, self.raid_id)

        await interaction.edit_original_response(embed=embed, view=self)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

    async def on_day_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        values = interaction.data.get("values", [])
        async with session_scope() as session:
            for v in values:
                await toggle_vote(session, self.raid_id, "day", v, interaction.user.id)
        await self.refresh_view(interaction)
        voter_name = interaction.user.display_name
        await interaction.followup.send(
            f"✅ Stimme aktualisiert für **{voter_name}**.",
            ephemeral=True,
        )

    async def on_time_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        values = interaction.data.get("values", [])
        async with session_scope() as session:
            for v in values:
                await toggle_vote(session, self.raid_id, "time", v, interaction.user.id)
        await self.refresh_view(interaction)
        voter_name = interaction.user.display_name
        await interaction.followup.send(
            f"✅ Stimme aktualisiert für **{voter_name}**.",
            ephemeral=True,
        )

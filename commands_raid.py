# commands_raid.py
import discord
from discord import app_commands
from sqlalchemy import select
from db import get_session
from models import Dungeon
from helpers import (
    send_temp,
    get_guild_settings,
    create_raid,
    get_options,
    build_summary,
    build_embed_for_raid,
    set_raid_message_id,
    raid_jump_url,
)
from views_raid import RaidCreateModal, RaidVoteView
from raidlist import schedule_raidlist_refresh, force_raidlist_refresh


def register_raid_commands(tree: app_commands.CommandTree, client: discord.Client):
    @tree.command(name="raidplan", description="Erstellt einen Raid Plan (Planer wird im konfigurierten Planer-Channel gepostet).")
    @app_commands.describe(dungeon="Dungeon Name (Tippen zum Suchen)")
    async def raidplan(interaction: discord.Interaction, dungeon: str):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        async with await get_session() as session:
            settings = await get_guild_settings(session, interaction.guild.id)
            if not settings:
                return await interaction.response.send_message("❌ Bitte zuerst `/settings` öffnen und alles setzen.", ephemeral=True)
            if not settings.participants_channel_id:
                return await interaction.response.send_message("❌ Bitte in `/settings` den Teilnehmerlisten-Channel setzen.", ephemeral=True)
            if not settings.planner_channel_id:
                return await interaction.response.send_message("❌ Bitte in `/settings` den Planer-Channel setzen.", ephemeral=True)

            planner_channel_id = settings.planner_channel_id

            res = await session.execute(select(Dungeon).where(Dungeon.is_active == True, Dungeon.name == dungeon))
            d = res.scalar_one_or_none()
            if not d:
                return await interaction.response.send_message("❌ Dungeon nicht gefunden (oder nicht aktiv). Tipp: nutze Autocomplete.", ephemeral=True)

        modal = RaidCreateModal(dungeon)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if not modal.result:
            return

        days_csv, times_csv, min_players = modal.result

        planner_channel = interaction.client.get_channel(planner_channel_id)
        if not isinstance(planner_channel, (discord.TextChannel, discord.Thread)):
            return await interaction.followup.send("❌ Planer-Channel ungültig (nicht gefunden).", ephemeral=True)

        async with await get_session() as session:
            raid = await create_raid(
                session=session,
                guild_id=interaction.guild.id,
                planner_channel_id=planner_channel_id,
                creator_id=interaction.user.id,
                dungeon=dungeon,
                days_csv=days_csv,
                times_csv=times_csv,
                min_players=min_players,
            )
            days, times = await get_options(session, raid.id)
            summary = await build_summary(session, raid.id)
            embed = await build_embed_for_raid(raid, summary)

        raid_view = RaidVoteView(raid.id, days, times)
        msg = await planner_channel.send(embed=embed, view=raid_view)

        async with await get_session() as session:
            await set_raid_message_id(session, raid.id, msg.id)

        client.add_view(raid_view, message_id=msg.id)

        # ✅ debounced raidlist update (fast, no spam)
        await schedule_raidlist_refresh(interaction.client, interaction.guild.id)

        await send_temp(interaction, f"✅ Raid erstellt: {raid_jump_url(raid)}")

    @raidplan.autocomplete("dungeon")
    async def raidplan_dungeon_autocomplete(interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        q = (current or "").strip().lower()
        async with await get_session() as session:
            res = await session.execute(
                select(Dungeon).where(Dungeon.is_active == True).order_by(Dungeon.sort_order.asc(), Dungeon.name.asc())
            )
            dungeons = res.scalars().all()
        if q:
            dungeons = [d for d in dungeons if q in d.name.lower()]
        return [app_commands.Choice(name=d.name, value=d.name) for d in dungeons[:25]]

    @tree.command(name="raidlist", description="Aktualisiert die persistente Raidlist sofort.")
    async def raidlist(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        await force_raidlist_refresh(interaction.client, interaction.guild.id)
        await send_temp(interaction, "✅ Raidlist aktualisiert.")

import discord
from discord import app_commands
from sqlalchemy import String, cast, or_, select

from db import session_scope
from helpers import delete_raid_cascade
from models import GuildSettings, Raid
from permissions import PRIVILEGED_USER_ID
from raidlist import force_raidlist_refresh, schedule_raidlist_refresh
from roles import cleanup_temp_role
from views_raid import cleanup_posted_slot_messages


def _is_privileged_debug_user(interaction: discord.Interaction) -> bool:
    return getattr(interaction.user, "id", None) == PRIVILEGED_USER_ID


async def _resolve_remote_guild_target(raw_value: str) -> tuple[int | None, str | None]:
    value = (raw_value or "").strip()
    if not value:
        return None, "❌ Bitte eine Guild-ID oder einen Guild-Namen angeben."

    if value.isdigit():
        return int(value), None

    async with session_scope() as session:
        exact_matches = (
            await session.execute(
                select(GuildSettings.guild_id)
                .where(GuildSettings.guild_name.is_not(None), GuildSettings.guild_name.ilike(value))
                .order_by(GuildSettings.guild_id.asc())
                .limit(2)
            )
        ).scalars().all()

        if len(exact_matches) == 1:
            return int(exact_matches[0]), None
        if len(exact_matches) > 1:
            return None, "❌ Mehrdeutiger Guild-Name. Bitte genaueren Namen oder die Guild-ID verwenden."

        partial_matches = (
            await session.execute(
                select(GuildSettings.guild_id)
                .where(GuildSettings.guild_name.is_not(None), GuildSettings.guild_name.ilike(f"%{value}%"))
                .order_by(GuildSettings.guild_name.asc().nulls_last(), GuildSettings.guild_id.asc())
                .limit(2)
            )
        ).scalars().all()

        if len(partial_matches) == 1:
            return int(partial_matches[0]), None
        if len(partial_matches) > 1:
            return None, "❌ Mehrere passende Guilds gefunden. Bitte den Namen präzisieren oder die Guild-ID verwenden."

    return None, "❌ Ungültige Guild-ID / kein passender Guild-Name gefunden."


async def _remote_guild_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if not _is_privileged_debug_user(interaction):
        return []

    query = (current or "").strip()
    async with session_scope() as session:
        stmt = select(GuildSettings).order_by(GuildSettings.guild_name.asc().nulls_last(), GuildSettings.guild_id.asc())

        if query:
            stmt = stmt.where(
                or_(
                    GuildSettings.guild_name.ilike(f"%{query}%"),
                    cast(GuildSettings.guild_id, String).ilike(f"%{query}%"),
                )
            )

        rows = (await session.execute(stmt.limit(25))).scalars().all()

    choices: list[app_commands.Choice[str]] = []
    for row in rows:
        guild_name = (row.guild_name or "").strip() or "(ohne guild_name in guild_settings)"
        label = f"{guild_name} ({row.guild_id})"
        choices.append(app_commands.Choice(name=label[:100], value=str(row.guild_id)))

    return choices


def register_remote_commands(tree: app_commands.CommandTree):
    @tree.command(name="remote_guilds", description="Zeigt bekannte Server für Fernwartung an (privileged).")
    async def remote_guilds(interaction: discord.Interaction):
        if not _is_privileged_debug_user(interaction):
            return await interaction.response.send_message("❌ Nur für den Debug-Owner erlaubt.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(GuildSettings).order_by(GuildSettings.guild_name.asc().nulls_last(), GuildSettings.guild_id.asc())
                )
            ).scalars().all()

        if not rows:
            return await interaction.followup.send("Keine Guild-Settings in der DB gefunden.", ephemeral=True)

        lines = []
        for row in rows[:50]:
            guild = interaction.client.get_guild(int(row.guild_id))
            live_state = "🟢 verbunden" if guild else "⚫ nicht verbunden"
            name = row.guild_name or (guild.name if guild else "(unbekannt)")
            lines.append(f"• `{row.guild_id}` — **{name}** ({live_state})")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @tree.command(name="remote_cancel_all_raids", description="Fernwartung: Alle offenen Raids eines Servers abbrechen.")
    @app_commands.describe(guild_id="Zielserver (Autocomplete aus guild_settings.guild_name) oder Guild-ID")
    async def remote_cancel_all_raids(interaction: discord.Interaction, guild_id: str):
        if not _is_privileged_debug_user(interaction):
            return await interaction.response.send_message("❌ Nur für den Debug-Owner erlaubt.", ephemeral=True)

        target_guild_id, resolve_error = await _resolve_remote_guild_target(guild_id)
        if target_guild_id is None:
            return await interaction.response.send_message(resolve_error or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        target_guild = interaction.client.get_guild(target_guild_id)

        async with session_scope() as session:
            raids = (
                await session.execute(select(Raid).where(Raid.guild_id == target_guild_id, Raid.status == "open"))
            ).scalars().all()

            for raid in raids:
                await cleanup_posted_slot_messages(session, interaction, raid.id)
                if target_guild is not None:
                    try:
                        await cleanup_temp_role(session, target_guild, raid)
                    except Exception:
                        pass
                await delete_raid_cascade(session, raid.id)

        await schedule_raidlist_refresh(interaction.client, target_guild_id)
        await interaction.followup.send(
            f"✅ {len(raids)} offene Raids in `{target_guild_id}` abgebrochen.",
            ephemeral=True,
        )

    @remote_cancel_all_raids.autocomplete("guild_id")
    async def remote_cancel_all_raids_autocomplete(interaction: discord.Interaction, current: str):
        return await _remote_guild_autocomplete(interaction, current)

    @tree.command(name="remote_raidlist", description="Fernwartung: Raidlist eines Zielservers neu aufbauen.")
    @app_commands.describe(guild_id="Zielserver (Autocomplete aus guild_settings.guild_name) oder Guild-ID")
    async def remote_raidlist(interaction: discord.Interaction, guild_id: str):
        if not _is_privileged_debug_user(interaction):
            return await interaction.response.send_message("❌ Nur für den Debug-Owner erlaubt.", ephemeral=True)

        target_guild_id, resolve_error = await _resolve_remote_guild_target(guild_id)
        if target_guild_id is None:
            return await interaction.response.send_message(resolve_error or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        await force_raidlist_refresh(interaction.client, target_guild_id)
        await interaction.followup.send(f"✅ Raidlist für `{target_guild_id}` aktualisiert.", ephemeral=True)

    @remote_raidlist.autocomplete("guild_id")
    async def remote_raidlist_autocomplete(interaction: discord.Interaction, current: str):
        return await _remote_guild_autocomplete(interaction, current)

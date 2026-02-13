import discord
from discord import app_commands
from sqlalchemy import select

from db import session_scope
from models import RaidAttendance
from permissions import admin_or_privileged_check


_STATUS_CHOICES = [
    app_commands.Choice(name="anwesend", value="present"),
    app_commands.Choice(name="abwesend", value="absent"),
    app_commands.Choice(name="unsicher", value="pending"),
]


def _status_label(value: str) -> str:
    return {
        "present": "✅ anwesend",
        "absent": "❌ abwesend",
        "pending": "⏳ pending",
    }.get(value, value)


def register_attendance_commands(tree: app_commands.CommandTree):
    @tree.command(name="attendance_list", description="Zeigt Attendance/No-Show Status für einen Raid an.")
    @app_commands.describe(raid_id="Raid-ID (Display-ID aus dem Planner)")
    @admin_or_privileged_check()
    async def attendance_list(interaction: discord.Interaction, raid_id: int):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        async with session_scope() as session:
            rows = (await session.execute(
                select(RaidAttendance)
                .where(
                    RaidAttendance.guild_id == interaction.guild.id,
                    RaidAttendance.raid_display_id == raid_id,
                )
                .order_by(RaidAttendance.status.asc(), RaidAttendance.user_id.asc())
            )).scalars().all()

        if not rows:
            return await interaction.response.send_message(
                "Keine Attendance-Daten für diesen Raid gefunden.",
                ephemeral=True,
            )

        dungeon = rows[0].dungeon
        lines = [f"• <@{row.user_id}> — {_status_label(row.status)}" for row in rows[:80]]
        await interaction.response.send_message(
            f"**Attendance Raid `{raid_id}` · {dungeon}**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @tree.command(name="attendance_mark", description="Setzt Attendance-Status für einen User.")
    @app_commands.describe(
        raid_id="Raid-ID (Display-ID)",
        member="Mitglied",
        status="Attendance-Status",
    )
    @app_commands.choices(status=_STATUS_CHOICES)
    @admin_or_privileged_check()
    async def attendance_mark(
        interaction: discord.Interaction,
        raid_id: int,
        member: discord.Member,
        status: app_commands.Choice[str],
    ):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with session_scope() as session:
            row = (await session.execute(
                select(RaidAttendance).where(
                    RaidAttendance.guild_id == interaction.guild.id,
                    RaidAttendance.raid_display_id == raid_id,
                    RaidAttendance.user_id == member.id,
                )
            )).scalar_one_or_none()

            if row is None:
                return await interaction.followup.send(
                    "❌ Für diesen User gibt es keinen Attendance-Eintrag in diesem Raid.",
                    ephemeral=True,
                )

            row.status = status.value
            row.marked_by_user_id = interaction.user.id

        await interaction.followup.send(
            f"✅ Attendance gesetzt: {member.mention} → {_status_label(status.value)}",
            ephemeral=True,
        )

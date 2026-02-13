import discord
from discord import app_commands
import logging

from backup_sql import export_database_to_sql
from permissions import PRIVILEGED_USER_ID

log = logging.getLogger("dmw-raid-bot")


def _notify_log_channel(interaction: discord.Interaction, message: str) -> None:
    enqueue = getattr(interaction.client, "enqueue_discord_log", None)
    if callable(enqueue):
        enqueue(message)


def register_backup_commands(tree: app_commands.CommandTree):
    @tree.command(name="backup_db", description="Failsafe: Exportiert die Datenbank als SQL-Datei ins Repository.")
    async def backup_db(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)
        if getattr(interaction.user, "id", None) != PRIVILEGED_USER_ID:
            return await interaction.response.send_message("❌ Nur für den Privileged Owner.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        _notify_log_channel(interaction, f"[backup] Manueller Backup-Start durch user_id={interaction.user.id} guild_id={interaction.guild.id}")
        log.info("Manual backup started by user_id=%s guild_id=%s", interaction.user.id, interaction.guild.id)
        try:
            output_path = await export_database_to_sql()
        except Exception:
            _notify_log_channel(interaction, f"[backup] Manueller Backup fehlgeschlagen durch user_id={interaction.user.id}")
            log.exception("Manual /backup_db export failed")
            return await interaction.followup.send("❌ Backup fehlgeschlagen. Bitte Logs prüfen.", ephemeral=True)

        _notify_log_channel(interaction, f"[backup] Manueller Backup abgeschlossen: {output_path.as_posix()}")
        log.info("Manual backup completed at %s", output_path.as_posix())

        await interaction.followup.send(f"✅ DB Backup geschrieben: `{output_path.as_posix()}`", ephemeral=True)

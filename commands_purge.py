import asyncio
import discord
from discord import app_commands

def _bot_can_manage_channel_messages(me: discord.Member, channel: discord.abc.GuildChannel) -> bool:
    try:
        perms = channel.permissions_for(me)
        return perms.read_message_history and perms.manage_messages
    except Exception:
        return False

async def purge_bot_messages_in_channel(channel: discord.abc.Messageable, bot_user_id: int, limit_scan: int = 5000, sleep_s: float = 0.35) -> int:
    deleted = 0
    now = discord.utils.utcnow()
    bulk = []
    bulk_cutoff_seconds = 14 * 24 * 3600 - 60

    async for msg in channel.history(limit=limit_scan):
        if msg.author.id != bot_user_id:
            continue

        age_s = (now - msg.created_at).total_seconds()
        if age_s < bulk_cutoff_seconds:
            bulk.append(msg)
            if len(bulk) >= 100:
                try:
                    await channel.delete_messages(bulk)
                    deleted += len(bulk)
                except Exception:
                    for m in bulk:
                        try:
                            await m.delete()
                            deleted += 1
                            await asyncio.sleep(sleep_s)
                        except Exception:
                            pass
                bulk.clear()
        else:
            try:
                await msg.delete()
                deleted += 1
                await asyncio.sleep(sleep_s)
            except Exception:
                pass

    if bulk:
        try:
            await channel.delete_messages(bulk)
            deleted += len(bulk)
        except Exception:
            for m in bulk:
                try:
                    await m.delete()
                    deleted += 1
                    await asyncio.sleep(sleep_s)
                except Exception:
                    pass
    return deleted

def iter_all_text_channels_and_threads(guild: discord.Guild):
    for ch in guild.text_channels:
        yield ch
        for th in ch.threads:
            yield th

def register_purge_commands(tree: app_commands.CommandTree):
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="here (nur dieser Channel)", value="here"),
            app_commands.Choice(name="all (alle Text-Channels + Threads)", value="all"),
        ]
    )
    @tree.command(name="purgebot", description="Löscht Bot-Nachrichten (here oder all).")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purgebot(interaction: discord.Interaction, scope: app_commands.Choice[str]):
        if not interaction.guild or not interaction.client.user:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        me = interaction.guild.me
        if not me:
            return await interaction.followup.send("❌ Bot-Member nicht gefunden.", ephemeral=True)

        bot_id = interaction.client.user.id
        deleted_total = 0

        if scope.value == "here":
            channel = interaction.channel
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return await interaction.followup.send("❌ Nur in Text-Channels/Threads nutzbar.", ephemeral=True)
            if not _bot_can_manage_channel_messages(me, channel):
                return await interaction.followup.send("❌ Mir fehlen Rechte (Manage Messages + Read History) in diesem Channel.", ephemeral=True)

            deleted_total = await purge_bot_messages_in_channel(channel, bot_id)
            return await interaction.followup.send(f"🧹 Gelöscht: **{deleted_total}** Bot-Nachrichten in diesem Channel.", ephemeral=True)

        scanned = 0
        skipped = 0
        for ch in iter_all_text_channels_and_threads(interaction.guild):
            scanned += 1
            if isinstance(ch, (discord.TextChannel, discord.Thread)) and not _bot_can_manage_channel_messages(me, ch):
                skipped += 1
                continue
            try:
                deleted_total += await purge_bot_messages_in_channel(ch, bot_id)
            except Exception:
                skipped += 1

        await interaction.followup.send(
            f"🧹 Fertig. Gelöscht: **{deleted_total}** Bot-Nachrichten.\n"
            f"Durchsucht: {scanned} Channels/Threads | Übersprungen: {skipped} (keine Rechte/Fehler).",
            ephemeral=True,
        )

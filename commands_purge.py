import discord
from discord import app_commands

from permissions import admin_or_privileged_check


def _iter_purgeable_channels(guild: discord.Guild, me: discord.Member) -> list[discord.TextChannel]:
    return [c for c in guild.text_channels if c.permissions_for(me).read_message_history]


def register_purge_commands(tree: app_commands.CommandTree):

    @tree.command(name="purge", description="Löscht die letzten N Nachrichten (Admin).")
    @admin_or_privileged_check()
    async def purge(interaction: discord.Interaction, amount: int = 10):
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Nur im Textchannel nutzbar.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        amount = max(1, min(100, int(amount)))
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ {len(deleted)} Nachrichten gelöscht.", ephemeral=True)

    @tree.command(name="purgebot", description="Löscht Bot-Nachrichten im Channel oder serverweit (Admin).")
    @app_commands.describe(
        scope="`channel` = nur aktueller Channel, `server` = alle Textchannels im Server",
        limit="Max. Nachrichten je Channel, die geprüft werden (1-5000)",
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="channel", value="channel"),
        app_commands.Choice(name="server", value="server"),
    ])
    @admin_or_privileged_check()
    async def purgebot(
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        limit: int = 500,
    ):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        limit = max(1, min(5000, int(limit)))

        me = interaction.guild.me or interaction.guild.get_member(interaction.client.user.id)
        if not me:
            return await interaction.followup.send("❌ Bot-Mitglied im Server nicht gefunden.", ephemeral=True)

        if scope.value == "channel":
            if not isinstance(interaction.channel, discord.TextChannel):
                return await interaction.followup.send("❌ Dieser Command geht hier nur in Textchannels.", ephemeral=True)
            channels = [interaction.channel]
        else:
            channels = _iter_purgeable_channels(interaction.guild, me)

        total_deleted = 0
        touched_channels = 0

        for ch in channels:
            perms = ch.permissions_for(me)
            if not (perms.read_message_history and perms.manage_messages):
                continue

            deleted_here = 0
            async for msg in ch.history(limit=limit):
                if msg.author.id != interaction.client.user.id:
                    continue
                try:
                    await msg.delete()
                    deleted_here += 1
                except (discord.Forbidden, discord.NotFound):
                    continue

            if deleted_here > 0:
                touched_channels += 1
                total_deleted += deleted_here

        where = "aktuellen Channel" if scope.value == "channel" else f"{touched_channels} Channels"
        await interaction.followup.send(
            f"✅ {total_deleted} Bot-Nachrichten gelöscht ({where}, Limit je Channel: {limit}).",
            ephemeral=True,
        )

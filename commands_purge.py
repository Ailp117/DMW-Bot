import discord
from discord import app_commands

def register_purge_commands(tree: app_commands.CommandTree):

    @tree.command(name="purge", description="Löscht die letzten N Nachrichten (Admin).")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(interaction: discord.Interaction, amount: int = 10):
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Nur im Textchannel nutzbar.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        amount = max(1, min(100, int(amount)))
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ {len(deleted)} Nachrichten gelöscht.", ephemeral=True)

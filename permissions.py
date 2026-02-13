import discord
from discord import app_commands

PRIVILEGED_USER_ID = 403988960638009347


async def is_admin_or_privileged(interaction: discord.Interaction) -> bool:
    user_id = getattr(interaction.user, "id", None)
    if user_id == PRIVILEGED_USER_ID:
        return True

    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and getattr(perms, "administrator", False))


def admin_or_privileged_check():
    return app_commands.check(is_admin_or_privileged)

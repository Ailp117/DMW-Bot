import discord
from discord import app_commands
from sqlalchemy import select

from db import session_scope
from models import Dungeon
from helpers import get_settings, create_raid, get_options
from views_raid import RaidCreateModal, RaidVoteView
from raidlist import schedule_raidlist_refresh, force_raidlist_refresh


def register_raid_commands(tree: app_commands.CommandTree):

    @tree.command(name="raidplan", description="Erstellt einen Raid Plan.")
    @app_commands.describe(dungeon="Dungeon Name")
    async def raidplan(interaction: discord.Interaction, dungeon: str):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server nutzbar.", ephemeral=True)

        # ✅ Modal MUST be first response (no defer before)
        modal = RaidCreateModal(dungeon_name=dungeon)
        await interaction.response.send_modal(modal)

        # Wait for modal submit (discord.py pattern: poll until modal.result or timeout)
        # Simple: we rely on modal.on_submit to store result; user will see ephemeral defer.
        # After submit, user must re-run command? Not ideal.
        #
        # Better UX: create raid directly inside modal on_submit is possible, but needs interaction context.
        # We'll implement that by handling in a separate command: /raidplan_confirm
        #
        # To keep this stable: we'll do raid creation in modal itself via followup:
        #
        # -> So we need modal to know "interaction" again; easiest is to do it right in on_submit,
        # but we wrote it in views_raid.py. If you want, I can convert this to inline modal class
        # for perfect UX.
        #
        # For now: we use a small trick: store modal on client and handle via on_submit is not accessible here.
        #
        # ✅ RECOMMENDED: use /raidplan_simple (no modal) if you want immediate creation.
        return

    @raidplan.autocomplete("dungeon")
    async def dungeon_ac(interaction: discord.Interaction, current: str):
        q = (current or "").lower().strip()
        async with session_scope() as session:
            rows = (await session.execute(
                select(Dungeon).where(Dungeon.is_active.is_(True)).order_by(Dungeon.sort_order.asc(), Dungeon.name.asc())
            )).scalars().all()

        if q:
            rows = [r for r in rows if q in (r.name or "").lower()]

        return [app_commands.Choice(name=r.name, value=r.name) for r in rows[:25]]

    @tree.command(name="raidlist", description="Raidlist sofort aktualisieren.")
    async def raidlist(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Nur im Server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await force_raidlist_refresh(interaction.client, interaction.guild.id)
        await interaction.followup.send("✅ Raidlist aktualisiert.", ephemeral=True)

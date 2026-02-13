import unittest
from pathlib import Path


class MainStaleAndHelpSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('main.py').read_text(encoding='utf-8')

    def test_status_command_registered(self):
        self.assertIn('@self.tree.command(name="status"', self.src)
        self.assertIn("Server-Status", self.src)
        self.assertIn("Standard Mindestspieler", self.src)

    def test_help_command_registered(self):
        self.assertIn('@self.tree.command(name="help"', self.src)
        self.assertIn('`/raidplan`', self.src)
        self.assertIn('`/purgebot`', self.src)
        self.assertIn('`/help2`', self.src)
        self.assertIn("if getattr(interaction.user, \"id\", None)", self.src)

    def test_help2_command_registered(self):
        self.assertIn('@self.tree.command(name="help2"', self.src)
        self.assertIn('Anleitung wurde in diesen Channel gepostet', self.src)

    def test_restart_command_registered(self):
        self.assertIn('@self.tree.command(name="restart"', self.src)
        self.assertIn('asyncio.create_task(self._restart_process())', self.src)

    def test_command_sync_uses_database_guild_ids(self):
        self.assertIn('async def _get_configured_guild_ids', self.src)
        self.assertIn('select(GuildSettings.guild_id)', self.src)
        self.assertIn('await self._sync_commands_for_known_guilds()', self.src)

    def test_stale_cleanup_worker_present(self):
        self.assertIn('STALE_RAID_HOURS = 7 * 24', self.src)
        self.assertIn('async def cleanup_stale_raids_once', self.src)
        self.assertIn('async def _stale_raid_worker', self.src)
        self.assertIn('self.stale_raid_task = asyncio.create_task(self._stale_raid_worker())', self.src)


if __name__ == '__main__':
    unittest.main()

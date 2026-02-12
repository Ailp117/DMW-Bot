import unittest
from pathlib import Path


class MainStaleAndHelpSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('main.py').read_text(encoding='utf-8')

    def test_status_command_registered(self):
        self.assertIn('@self.tree.command(name="status"', self.src)
        self.assertIn('"📊 DMW Bot Status"', self.src)
        self.assertIn('Stale Cleanup', self.src)

    def test_help_command_registered(self):
        self.assertIn('@self.tree.command(name="help"', self.src)
        self.assertIn('`/raidplan`', self.src)
        self.assertIn('`/purgebot`', self.src)

    def test_stale_cleanup_worker_present(self):
        self.assertIn('STALE_RAID_HOURS = 7 * 24', self.src)
        self.assertIn('async def cleanup_stale_raids_once', self.src)
        self.assertIn('async def _stale_raid_worker', self.src)
        self.assertIn('self.stale_raid_task = asyncio.create_task(self._stale_raid_worker())', self.src)


if __name__ == '__main__':
    unittest.main()

import unittest
from pathlib import Path


class MemberlistRestoreSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_src = Path('main.py').read_text(encoding='utf-8')
        cls.views_src = Path('views_raid.py').read_text(encoding='utf-8')

    def test_on_ready_restores_memberlists_once(self):
        self.assertIn('self._initial_memberlist_restore_done = False', self.main_src)
        self.assertIn('async def _restore_memberlists_for_all_guilds', self.main_src)
        self.assertIn('await self._restore_memberlists_for_all_guilds()', self.main_src)

    def test_sync_memberlists_helper_exists(self):
        self.assertIn('async def sync_memberlists_for_raid', self.views_src)
        self.assertIn('await session.delete(row)', self.views_src)
        self.assertIn('await _mirror_memberlist_debug_for_guild(', self.views_src)


if __name__ == '__main__':
    unittest.main()

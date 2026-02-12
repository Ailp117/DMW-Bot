import unittest
from pathlib import Path


class PersistentViewRestoreSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('main.py').read_text(encoding='utf-8')

    def test_setup_hook_uses_safe_restore_guard(self):
        self.assertIn('getattr(self, "restore_persistent_raid_views", None)', self.src)
        self.assertIn('if callable(restore_views):', self.src)

    def test_no_direct_unprotected_restore_call(self):
        self.assertNotIn('await self.restore_persistent_raid_views()', self.src)

    def test_restore_method_exists_and_is_called(self):
        self.assertIn('async def restore_persistent_raid_views', self.src)
        self.assertIn('self.add_view(RaidVoteView(raid.id, days, times))', self.src)
        self.assertIn('await restore_views()', self.src)


if __name__ == '__main__':
    unittest.main()

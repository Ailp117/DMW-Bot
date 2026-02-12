import unittest
from pathlib import Path


class PersistentViewRestoreSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('main.py').read_text(encoding='utf-8')

    def test_restore_method_exists_and_is_called(self):
        self.assertIn('async def restore_persistent_raid_views', self.src)
        self.assertIn('self.add_view(RaidVoteView(raid.id, days, times))', self.src)
        self.assertIn('await self.restore_persistent_raid_views()', self.src)


if __name__ == '__main__':
    unittest.main()

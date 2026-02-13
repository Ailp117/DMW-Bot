import unittest
from pathlib import Path


class MemberlistMinZeroSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('views_raid.py').read_text(encoding='utf-8')

    def test_zero_min_players_maps_to_threshold_one(self):
        self.assertIn('def _memberlist_threshold(min_players: int) -> int:', self.src)
        self.assertIn('return min_players if min_players > 0 else 1', self.src)
        self.assertIn('threshold = _memberlist_threshold(raid.min_players)', self.src)
        self.assertIn('if len(users) < threshold:', self.src)

    def test_refresh_calls_sync_even_with_zero_min_players(self):
        self.assertIn('if s.participants_channel_id:', self.src)
        self.assertIn('await sync_memberlists_for_raid(interaction.client, interaction.guild, self.raid_id)', self.src)


if __name__ == '__main__':
    unittest.main()

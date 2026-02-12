import unittest

from leveling import calculate_level_from_xp, xp_needed_for_level


class LevelingTests(unittest.TestCase):
    def test_xp_needed_for_level_progressive(self):
        self.assertEqual(xp_needed_for_level(0), 0)
        self.assertEqual(xp_needed_for_level(1), 100)
        self.assertEqual(xp_needed_for_level(2), 250)
        self.assertEqual(xp_needed_for_level(3), 450)

    def test_calculate_level_from_xp_progressive(self):
        self.assertEqual(calculate_level_from_xp(0), 0)
        self.assertEqual(calculate_level_from_xp(99), 0)
        self.assertEqual(calculate_level_from_xp(100), 1)
        self.assertEqual(calculate_level_from_xp(249), 1)
        self.assertEqual(calculate_level_from_xp(250), 2)
        self.assertEqual(calculate_level_from_xp(449), 2)
        self.assertEqual(calculate_level_from_xp(450), 3)

    def test_calculate_level_from_large_xp(self):
        self.assertEqual(calculate_level_from_xp(247_450), 98)
        self.assertEqual(calculate_level_from_xp(252_450), 99)
        self.assertEqual(calculate_level_from_xp(257_499), 99)
        self.assertEqual(calculate_level_from_xp(257_500), 100)


if __name__ == '__main__':
    unittest.main()

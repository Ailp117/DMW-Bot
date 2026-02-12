import ast
import unittest
from pathlib import Path


class ViewsRaidRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('views_raid.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.src)

    def test_raid_vote_view_does_not_define_async_private_refresh(self):
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == 'RaidVoteView':
                async_names = {n.name for n in node.body if isinstance(n, ast.AsyncFunctionDef)}
                self.assertNotIn('_refresh', async_names)
                self.assertIn('refresh_view', async_names)
                return
        self.fail('RaidVoteView class not found')

    def test_finish_button_cleans_up_posted_slot_messages(self):
        self.assertIn('await cleanup_posted_slot_messages(session, interaction, raid.id)', self.src)


if __name__ == '__main__':
    unittest.main()

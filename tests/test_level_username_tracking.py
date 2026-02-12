import ast
import unittest
from pathlib import Path


class LevelUsernameTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models_src = Path("models.py").read_text(encoding="utf-8")
        cls.main_src = Path("main.py").read_text(encoding="utf-8")
        cls.models_tree = ast.parse(cls.models_src)

    def test_user_level_model_has_username_column(self):
        for node in self.models_tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "UserLevel":
                assignments = [
                    n for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                ]
                field_names = {a.target.id for a in assignments}
                self.assertIn("username", field_names)
                return
        self.fail("UserLevel class not found")

    def test_level_updating_sets_username(self):
        self.assertIn("user_level.username = _member_username_in_guild(member)", self.main_src)
        self.assertIn("user_level.username = _member_username_in_guild(message.author)", self.main_src)


if __name__ == "__main__":
    unittest.main()

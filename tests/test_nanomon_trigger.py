import ast
import unittest
from pathlib import Path


class NanomonTriggerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('main.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.src)

    def test_has_keyword_pattern_with_word_boundary(self):
        self.assertIn(r'\bnanomon\b', self.src)

    def test_keyword_check_uses_casefold(self):
        self.assertIn('.casefold()', self.src)

    def test_has_on_message_reply_with_image_url(self):
        self.assertIn('async def on_message', self.src)
        self.assertIn('await message.reply(NANOMON_IMAGE_URL, mention_author=False)', self.src)


if __name__ == '__main__':
    unittest.main()

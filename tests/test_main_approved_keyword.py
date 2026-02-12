import unittest
from pathlib import Path


class MainApprovedKeywordSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path('main.py').read_text(encoding='utf-8')

    def test_approved_keyword_constants_and_helper_present(self):
        self.assertIn('APPROVED_GIF_URL = "https://media1.tenor.com/m/l8waltLHrxcAAAAC/approved.gif"', self.src)
        self.assertIn('APPROVED_PATTERN = re.compile(r"\\bapproved\\b")', self.src)
        self.assertIn('def contains_approved_keyword(content: str) -> bool:', self.src)

    def test_approved_reply_in_on_message(self):
        self.assertIn('if contains_approved_keyword(message.content):', self.src)
        self.assertIn('await message.reply(APPROVED_GIF_URL, mention_author=False)', self.src)


if __name__ == '__main__':
    unittest.main()

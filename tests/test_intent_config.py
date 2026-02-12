import unittest
from pathlib import Path


class IntentConfigSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_src = Path('config.py').read_text(encoding='utf-8')
        cls.main_src = Path('main.py').read_text(encoding='utf-8')

    def test_message_content_intent_is_env_configurable(self):
        self.assertIn('ENABLE_MESSAGE_CONTENT_INTENT', self.config_src)
        self.assertIn('INTENTS.message_content = ENABLE_MESSAGE_CONTENT_INTENT', self.main_src)

    def test_on_message_short_circuits_when_intent_disabled(self):
        self.assertIn('if not ENABLE_MESSAGE_CONTENT_INTENT:', self.main_src)


if __name__ == '__main__':
    unittest.main()

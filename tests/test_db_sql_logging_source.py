import unittest
from pathlib import Path


class DiscordLogLevelSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_src = Path('main.py').read_text(encoding='utf-8')
        cls.config_src = Path('config.py').read_text(encoding='utf-8')

    def test_discord_log_level_config_exists(self):
        self.assertIn('DISCORD_LOG_LEVEL = os.getenv("DISCORD_LOG_LEVEL", "DEBUG").strip().upper()', self.config_src)

    def test_discord_handler_uses_configured_level(self):
        self.assertIn('discord_level = getattr(logging, DISCORD_LOG_LEVEL, logging.DEBUG)', self.main_src)
        self.assertIn('handler = _DiscordQueueHandler(level=discord_level)', self.main_src)


if __name__ == '__main__':
    unittest.main()

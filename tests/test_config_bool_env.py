import importlib
import os
import unittest


class ConfigEnvBoolTests(unittest.TestCase):
    def _load_with_env(self, value):
        old = os.environ.get("ENABLE_MESSAGE_CONTENT_INTENT")
        try:
            if value is None:
                os.environ.pop("ENABLE_MESSAGE_CONTENT_INTENT", None)
            else:
                os.environ["ENABLE_MESSAGE_CONTENT_INTENT"] = value
            import config
            importlib.reload(config)
            return config.ENABLE_MESSAGE_CONTENT_INTENT
        finally:
            if old is None:
                os.environ.pop("ENABLE_MESSAGE_CONTENT_INTENT", None)
            else:
                os.environ["ENABLE_MESSAGE_CONTENT_INTENT"] = old
            import config
            importlib.reload(config)

    def test_truthy_values_enable_intent(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(self._load_with_env(value))

    def test_falsy_values_disable_intent(self):
        for value in ("0", "false", "no", "off", "random"):
            with self.subTest(value=value):
                self.assertFalse(self._load_with_env(value))

    def test_default_is_enabled(self):
        self.assertTrue(self._load_with_env(None))


if __name__ == "__main__":
    unittest.main()

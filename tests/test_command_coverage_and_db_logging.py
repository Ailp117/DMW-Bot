import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import db
from commands_admin import register_admin_commands
from commands_purge import register_purge_commands
from commands_raid import register_raid_commands
from commands_remote import register_remote_commands
from commands_backup import register_backup_commands
from models import UserLevel


class FakeCommand:
    def __init__(self, callback):
        self.callback = callback
        self.autocomplete_handlers = {}

    def autocomplete(self, param_name):
        def decorator(func):
            self.autocomplete_handlers[param_name] = func
            return func

        return decorator


class FakeTree:
    def __init__(self):
        self.commands = {}

    def command(self, *, name, description):
        def decorator(func):
            self.commands[name] = {
                "description": description,
                "command": FakeCommand(func),
            }
            return self.commands[name]["command"]

        return decorator


class CommandCoverageAndDbLoggingTests(unittest.TestCase):
    def test_all_declared_slash_commands_register_in_modules(self):
        tree = FakeTree()

        register_admin_commands(tree)
        register_raid_commands(tree)
        register_purge_commands(tree)
        register_remote_commands(tree)
        register_backup_commands(tree)

        self.assertEqual(
            set(tree.commands.keys()),
            {
                "raidplan",
                "raidlist",
                "dungeonlist",
                "cancel_all_raids",
                "purge",
                "purgebot",
                "remote_guilds",
                "remote_cancel_all_raids",
                "remote_raidlist",
                "backup_db",
            },
        )

        self.assertIn("dungeon", tree.commands["raidplan"]["command"].autocomplete_handlers)

    def test_database_logging_serializes_payloads(self):
        long_name = "x" * 200
        new_entity = UserLevel(guild_id=1, user_id=2, username=long_name, xp=10, level=1)
        dirty_entity = UserLevel(guild_id=1, user_id=3, username="tester", xp=20, level=2)
        deleted_entity = UserLevel(guild_id=2, user_id=4, username=None, xp=0, level=0)
        fake_session = SimpleNamespace(new=[new_entity], dirty=[dirty_entity], deleted=[deleted_entity])

        with patch.object(db.log, "debug") as debug_mock:
            db._log_unit_of_work(fake_session)

        debug_mock.assert_called_once()
        args = debug_mock.call_args.args
        self.assertEqual(args[0], "[to-db] unit_of_work new=%s dirty=%s deleted=%s")

        new_items, dirty_items, deleted_items = args[1], args[2], args[3]
        self.assertEqual(new_items[0]["__model__"], "UserLevel")
        self.assertTrue(new_items[0]["username"].endswith("..."))
        self.assertEqual(len(new_items[0]["username"]), 120)
        self.assertEqual(dirty_items[0]["username"], "tester")
        self.assertIsNone(deleted_items[0]["username"])

    def test_database_logging_skips_empty_unit_of_work(self):
        fake_session = SimpleNamespace(new=[], dirty=[], deleted=[])

        with patch.object(db.log, "debug") as debug_mock:
            db._log_unit_of_work(fake_session)

        debug_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import main


class _DummyTask:
    def done(self):
        return False

    def cancel(self):
        return None


class CommandSyncResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = main.RaidBot()

    async def asyncTearDown(self):
        main.log.removeHandler(self.bot._discord_log_handler)

    async def test_setup_hook_registers_all_commands(self):
        dummy_task = _DummyTask()

        with (
            patch.object(main, "ensure_schema", AsyncMock()),
            patch.object(main, "try_acquire_singleton_lock", AsyncMock(return_value=True)),
            patch.object(self.bot, "restore_persistent_raid_views", AsyncMock()),
            patch("main.asyncio.create_task", side_effect=lambda coro: (coro.close(), dummy_task)[1]),
        ):
            await self.bot.setup_hook()

        command_names = {cmd.name for cmd in self.bot.tree.get_commands()}
        self.assertEqual(
            command_names,
            {
                "settings",
                "status",
                "help",
                "help2",
                "restart",
                "raidplan",
                "raidlist",
                "dungeonlist",
                "cancel_all_raids",
                "purge",
                "purgebot",
                "remote_guilds",
                "remote_cancel_all_raids",
                "remote_raidlist",
            },
        )

    async def test_on_ready_triggers_sync_and_initial_refresh_once(self):
        self.bot.log_forwarder_task = _DummyTask()

        self.bot._cleanup_removed_guild_data_on_startup = AsyncMock()
        self.bot._resolve_log_channel = AsyncMock(return_value=None)
        self.bot._sync_commands_for_known_guilds = AsyncMock()
        self.bot._refresh_raidlists_for_all_guilds = AsyncMock()

        await self.bot.on_ready()
        await self.bot.on_ready()

        self.bot._cleanup_removed_guild_data_on_startup.assert_awaited_once()
        self.bot._sync_commands_for_known_guilds.assert_awaited_once()
        self.bot._refresh_raidlists_for_all_guilds.assert_awaited_once()

    async def test_on_guild_join_syncs_and_refreshes(self):
        guild = SimpleNamespace(id=12345)

        with (
            patch.object(self.bot.tree, "sync", AsyncMock()) as sync_mock,
            patch.object(main, "force_raidlist_refresh", AsyncMock()) as refresh_mock,
        ):
            await self.bot.on_guild_join(guild)

        sync_mock.assert_awaited_once()
        refresh_mock.assert_awaited_once_with(self.bot, guild.id)

    async def test_refresh_raidlists_for_all_guilds_attempts_every_guild(self):
        guilds = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]

        async def _refresh(_bot, guild_id):
            if guild_id == 2:
                raise RuntimeError("boom")

        with (
            patch.object(type(self.bot), "guilds", new_callable=PropertyMock, return_value=guilds),
            patch.object(main, "force_raidlist_refresh", side_effect=_refresh) as refresh_mock,
        ):
            await self.bot._refresh_raidlists_for_all_guilds()

        self.assertEqual(refresh_mock.await_count, 3)

    async def test_setup_hook_starts_self_test_worker_task(self):
        created = []

        class _Task:
            def done(self):
                return False

            def cancel(self):
                return None

        def _create_task(coro):
            created.append(coro.cr_code.co_name)
            coro.close()
            return _Task()

        with (
            patch.object(main, "ensure_schema", AsyncMock()),
            patch.object(main, "try_acquire_singleton_lock", AsyncMock(return_value=True)),
            patch.object(self.bot, "restore_persistent_raid_views", AsyncMock()),
            patch("main.asyncio.create_task", side_effect=_create_task),
        ):
            await self.bot.setup_hook()

        self.assertIn("_self_test_worker", created)

    async def test_run_self_tests_once_queries_same_database_session_scope(self):
        fake_commands = [SimpleNamespace(name=n) for n in [
            "settings", "status", "help", "help2", "restart",
            "raidplan", "raidlist", "dungeonlist", "cancel_all_raids", "purge", "purgebot",
            "remote_guilds", "remote_cancel_all_raids", "remote_raidlist",
        ]]

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

            def scalar_one(self):
                return len(self._rows)

        class _Session:
            def __init__(self):
                self.calls = 0

            async def execute(self, _query):
                self.calls += 1
                return _Result([1, 2] if self.calls == 1 else [10])

        fake_session = _Session()

        @asynccontextmanager
        async def _fake_session_scope():
            yield fake_session

        with (
            patch.object(self.bot.tree, "get_commands", return_value=fake_commands),
            patch.object(main, "session_scope", _fake_session_scope),
        ):
            await self.bot._run_self_tests_once()

        self.assertEqual(fake_session.calls, 2)
        self.assertIsNotNone(self.bot.last_self_test_ok_at)
        self.assertIsNone(self.bot.last_self_test_error)



if __name__ == "__main__":
    unittest.main()

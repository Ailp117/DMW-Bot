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
            patch.object(self.bot, "_run_boot_smoke_checks", AsyncMock(return_value={"required_tables": 7, "open_raids": 0, "guild_settings_rows": 0})),
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
                "template_config",
                "attendance_list",
                "attendance_mark",
                "backup_db",
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

    async def test_sync_commands_for_known_guilds_runs_global_fallback_sync(self):
        guilds = [SimpleNamespace(id=111), SimpleNamespace(id=222)]

        with (
            patch.object(self.bot, "_get_configured_guild_ids", AsyncMock(return_value=[])),
            patch.object(type(self.bot), "guilds", new_callable=PropertyMock, return_value=guilds),
            patch.object(self.bot.tree, "sync", AsyncMock()) as sync_mock,
        ):
            await self.bot._sync_commands_for_known_guilds()

        self.assertEqual(sync_mock.await_count, 3)
        sync_mock.assert_any_await(guild=main.discord.Object(id=111))
        sync_mock.assert_any_await(guild=main.discord.Object(id=222))
        sync_mock.assert_any_await()

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
            patch.object(self.bot, "_run_boot_smoke_checks", AsyncMock(return_value={"required_tables": 7, "open_raids": 0, "guild_settings_rows": 0})),
            patch.object(self.bot, "restore_persistent_raid_views", AsyncMock()),
            patch("main.asyncio.create_task", side_effect=_create_task),
        ):
            await self.bot.setup_hook()

        self.assertIn("_self_test_worker", created)

    def test_command_registry_health_detects_unexpected_commands(self):
        fake_commands = [SimpleNamespace(name=n) for n in [
            *sorted(main.EXPECTED_SLASH_COMMANDS),
            "unexpected_demo",
        ]]

        with patch.object(self.bot.tree, "get_commands", return_value=fake_commands):
            registered, missing, unexpected = self.bot._command_registry_health()

        self.assertIn("unexpected_demo", registered)
        self.assertEqual(missing, [])
        self.assertEqual(unexpected, ["unexpected_demo"])

    def test_build_ready_announcement_mentions_priority_user_when_configured(self):
        with patch.object(main, "PRIVILEGED_USER_ID", 987654321):
            message = self.bot._build_ready_announcement()

        self.assertIn("<@987654321>", message)
        self.assertIn("in Bereitschaft", message)

    async def test_on_ready_sends_ready_announcement_only_once(self):
        self.bot.log_channel = object()
        self.bot.log_forwarder_task = _DummyTask()

        self.bot._cleanup_removed_guild_data_on_startup = AsyncMock()
        self.bot._sync_commands_for_known_guilds = AsyncMock()
        self.bot._refresh_raidlists_for_all_guilds = AsyncMock()
        self.bot._restore_memberlists_for_all_guilds = AsyncMock()

        await self.bot.on_ready()
        await self.bot.on_ready()

        queued = []
        while not self.bot.log_forward_queue.empty():
            queued.append(self.bot.log_forward_queue.get_nowait())

        ready_messages = [m for m in queued if "in Bereitschaft" in m]
        self.assertEqual(len(ready_messages), 1)

    async def test_run_self_tests_once_queries_same_database_session_scope(self):
        fake_commands = [SimpleNamespace(name=n) for n in [
            "settings", "status", "help", "help2", "restart",
            "raidplan", "raidlist", "dungeonlist", "cancel_all_raids", "purge", "purgebot",
            "remote_guilds", "remote_cancel_all_raids", "remote_raidlist",
            "template_config",
            "attendance_list", "attendance_mark", "backup_db",
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


    async def test_setup_hook_runs_boot_smoke_checks(self):
        dummy_task = _DummyTask()

        with (
            patch.object(main, "ensure_schema", AsyncMock()),
            patch.object(main, "try_acquire_singleton_lock", AsyncMock(return_value=True)),
            patch.object(self.bot, "_run_boot_smoke_checks", AsyncMock(return_value={"required_tables": 7, "open_raids": 0, "guild_settings_rows": 1})) as smoke_mock,
            patch.object(self.bot, "restore_persistent_raid_views", AsyncMock()),
            patch("main.asyncio.create_task", side_effect=lambda coro: (coro.close(), dummy_task)[1]),
        ):
            await self.bot.setup_hook()

        smoke_mock.assert_awaited_once()
        self.assertIsInstance(self.bot.boot_smoke_stats, dict)

    async def test_run_boot_smoke_checks_returns_stats(self):
        class _Result:
            def __init__(self, rows=None, scalar=None):
                self._rows = rows or []
                self._scalar = scalar

            def scalars(self):
                return self

            def all(self):
                return self._rows

            def scalar_one(self):
                return self._scalar

        class _Session:
            def __init__(self):
                self.calls = 0

            async def execute(self, _query):
                self.calls += 1
                if self.calls == 1:
                    return _Result(scalar=1)
                if self.calls == 2:
                    return _Result(rows=list(main.REQUIRED_BOOT_TABLES))
                if self.calls == 3:
                    return _Result(scalar=2)
                return _Result(scalar=4)

        fake_session = _Session()

        @asynccontextmanager
        async def _fake_session_scope():
            yield fake_session

        with patch.object(main, "session_scope", _fake_session_scope):
            stats = await self.bot._run_boot_smoke_checks()

        self.assertEqual(stats["required_tables"], len(main.REQUIRED_BOOT_TABLES))
        self.assertEqual(stats["open_raids"], 2)
        self.assertEqual(stats["guild_settings_rows"], 4)


if __name__ == "__main__":
    unittest.main()

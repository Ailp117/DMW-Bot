from __future__ import annotations

import sys

import pytest

from bot.runner import BotRunner, RunnerConfig


def _runner(target: str) -> BotRunner:
    config = RunnerConfig(
        target=target,
        max_runtime_seconds=1,
        restart_delay_seconds=1,
        max_backoff_seconds=1,
        min_uptime_seconds=1,
        max_quick_failures=1,
    )
    return BotRunner(config)


def test_runner_builds_module_target_command():
    runner = _runner("module:bot.runtime")
    assert runner._build_child_command() == [sys.executable, "-m", "bot.runtime"]


def test_runner_builds_script_target_command():
    runner = _runner("bot/runtime.py")
    assert runner._build_child_command() == [sys.executable, "bot/runtime.py"]


def test_runner_rejects_empty_module_target():
    runner = _runner("module:")
    with pytest.raises(ValueError, match="module:<dotted.path>"):
        runner._build_child_command()

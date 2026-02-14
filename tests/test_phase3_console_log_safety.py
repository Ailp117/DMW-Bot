from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot


@pytest.mark.asyncio
async def test_execute_console_command_ignores_empty_slash_message():
    bot = object.__new__(RewriteDiscordBot)
    message = SimpleNamespace(content="/", channel=SimpleNamespace())

    handled = await RewriteDiscordBot._execute_console_command(bot, message)

    assert handled is False


def test_enqueue_discord_log_drops_oldest_when_queue_is_full():
    bot = object.__new__(RewriteDiscordBot)
    bot.log_forward_queue = asyncio.Queue(maxsize=3)
    bot.pending_log_buffer = deque(maxlen=250)
    bot.log_forwarder_active = True

    for idx in range(5):
        RewriteDiscordBot.enqueue_discord_log(bot, f"msg-{idx}")

    queued: list[str] = []
    while not bot.log_forward_queue.empty():
        queued.append(bot.log_forward_queue.get_nowait())

    assert queued == ["msg-2", "msg-3", "msg-4"]


def test_flush_pending_logs_respects_queue_bound():
    bot = object.__new__(RewriteDiscordBot)
    bot.log_forward_queue = asyncio.Queue(maxsize=2)
    bot.pending_log_buffer = deque(["first", "second", "third"], maxlen=250)

    RewriteDiscordBot._flush_pending_logs(bot)

    queued: list[str] = []
    while not bot.log_forward_queue.empty():
        queued.append(bot.log_forward_queue.get_nowait())

    assert queued == ["second", "third"]
    assert not bot.pending_log_buffer

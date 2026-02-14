from __future__ import annotations

import pytest

from discord.safety import safe_defer, safe_edit_message, safe_send_initial


class _FakeResponse:
    def __init__(self, done: bool = False):
        self._done = done
        self.deferred = 0
        self.sent = []

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False):
        self.deferred += 1
        self._done = True

    async def send_message(self, content: str, *, ephemeral: bool = False, **kwargs):
        self.sent.append((content, ephemeral, kwargs))
        self._done = True


class _FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content: str, *, ephemeral: bool = False, **kwargs):
        self.sent.append((content, ephemeral, kwargs))


class _FakeInteraction:
    def __init__(self, done: bool = False):
        self.response = _FakeResponse(done=done)
        self.followup = _FakeFollowup()


class NotFound(Exception):
    pass


class _FakeMessage:
    def __init__(self, should_fail: bool):
        self.should_fail = should_fail

    async def edit(self, **kwargs):
        if self.should_fail:
            raise NotFound("gone")


@pytest.mark.asyncio
async def test_safe_defer_is_idempotent():
    interaction = _FakeInteraction(done=False)

    first = await safe_defer(interaction, ephemeral=True)
    second = await safe_defer(interaction, ephemeral=True)

    assert first is True
    assert second is False
    assert interaction.response.deferred == 1


@pytest.mark.asyncio
async def test_safe_send_initial_falls_back_to_followup_when_done():
    interaction = _FakeInteraction(done=True)

    ok = await safe_send_initial(interaction, "hello", ephemeral=True)

    assert ok is True
    assert interaction.followup.sent == [("hello", True, {})]


@pytest.mark.asyncio
async def test_safe_edit_message_handles_not_found():
    ok = await safe_edit_message(_FakeMessage(should_fail=True), content="x")
    assert ok is False

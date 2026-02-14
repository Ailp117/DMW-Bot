from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


_RESPONSE_ERRORS = {
    "InteractionResponded",
    "HTTPException",
    "NotFound",
    "Forbidden",
}


@dataclass(slots=True)
class InteractionAckState:
    interaction_id: int
    acknowledged: bool = False


class InteractionAcker:
    """Per-interaction ack guard to prevent double-respond races."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._states: dict[int, InteractionAckState] = {}

    async def mark_or_get(self, interaction_id: int) -> bool:
        async with self._lock:
            state = self._states.get(interaction_id)
            if state is None:
                self._states[interaction_id] = InteractionAckState(interaction_id=interaction_id, acknowledged=True)
                return True
            if state.acknowledged:
                return False
            state.acknowledged = True
            return True


def _is_response_error(exc: Exception) -> bool:
    return exc.__class__.__name__ in _RESPONSE_ERRORS


async def safe_defer(interaction: Any, *, ephemeral: bool = False) -> bool:
    response = getattr(interaction, "response", None)
    if response is None:
        return False
    is_done = getattr(response, "is_done", None)
    if callable(is_done) and is_done():
        return False

    try:
        await response.defer(ephemeral=ephemeral)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if _is_response_error(exc):
            return False
        return False


async def safe_send_initial(
    interaction: Any,
    content: str,
    *,
    ephemeral: bool = False,
    **kwargs: Any,
) -> bool:
    response = getattr(interaction, "response", None)
    if response is None:
        return False

    is_done = getattr(response, "is_done", None)
    done = callable(is_done) and is_done()
    if done:
        return await safe_followup(interaction, content, ephemeral=ephemeral, **kwargs)

    try:
        await response.send_message(content, ephemeral=ephemeral, **kwargs)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if not _is_response_error(exc):
            return False
        return await safe_followup(interaction, content, ephemeral=ephemeral, **kwargs)


async def safe_followup(interaction: Any, content: str, *, ephemeral: bool = False, **kwargs: Any) -> bool:
    followup = getattr(interaction, "followup", None)
    if followup is None:
        return False

    try:
        await followup.send(content, ephemeral=ephemeral, **kwargs)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if _is_response_error(exc):
            return False
        return False


async def safe_edit_interaction_original(interaction: Any, **kwargs: Any) -> bool:
    edit_fn = getattr(interaction, "edit_original_response", None)
    if edit_fn is None:
        return False

    try:
        await edit_fn(**kwargs)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if _is_response_error(exc):
            return False
        return False


async def safe_edit_message(message: Any, **kwargs: Any) -> bool:
    try:
        await message.edit(**kwargs)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if _is_response_error(exc):
            return False
        return False


async def safe_delete_message(message: Any) -> bool:
    try:
        await message.delete()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if _is_response_error(exc):
            return False
        return False

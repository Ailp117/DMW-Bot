from __future__ import annotations

from services.startup_service import EXPECTED_SLASH_COMMANDS


COMMAND_NAMES = tuple(sorted(EXPECTED_SLASH_COMMANDS))


def registered_command_names() -> list[str]:
    return list(COMMAND_NAMES)

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from db.models import REQUIRED_BOOT_TABLES
from db.repository import InMemoryRepository


EXPECTED_SLASH_COMMANDS = {
    "settings",
    "status",
    "help",
    "help2",
    "restart",
    "raidplan",
    "raid_finish",
    "raidlist",
    "dungeonlist",
    "cancel_all_raids",
    "purge",
    "purgebot",
    "remote_guilds",
    "remote_cancel_all_raids",
    "remote_raidlist",
    "remote_rebuild_memberlists",
    "template_config",
    "backup_db",
}


@dataclass(slots=True)
class BootSmokeStats:
    required_tables: int
    open_raids: int
    guild_settings_rows: int


class SingletonGate:
    def __init__(self) -> None:
        self._held = False

    async def try_acquire(self) -> bool:
        if self._held:
            return False
        self._held = True
        return True


def command_registry_health(registered_commands: Iterable[str]) -> tuple[list[str], list[str], list[str]]:
    registered = sorted(set(registered_commands))
    reg_set = set(registered)
    missing = sorted(EXPECTED_SLASH_COMMANDS - reg_set)
    unexpected = sorted(reg_set - EXPECTED_SLASH_COMMANDS)
    return registered, missing, unexpected


def run_boot_smoke_checks(repo: InMemoryRepository, existing_tables: Iterable[str]) -> BootSmokeStats:
    existing = set(existing_tables)
    missing = [table for table in REQUIRED_BOOT_TABLES if table not in existing]
    if missing:
        raise RuntimeError(f"Missing required DB tables: {', '.join(missing)}")

    open_raids = len(repo.list_open_raids())
    guild_settings_rows = len(repo.settings)

    return BootSmokeStats(
        required_tables=len(REQUIRED_BOOT_TABLES),
        open_raids=open_raids,
        guild_settings_rows=guild_settings_rows,
    )

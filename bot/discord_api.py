from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from typing import Any, cast


def _import_discord_api_module():
    cwd = os.path.abspath(os.getcwd())
    search_path: list[str] = []
    for raw in sys.path:
        absolute = os.path.abspath(raw or os.getcwd())
        if absolute == cwd:
            continue
        search_path.append(raw)

    spec = importlib.machinery.PathFinder.find_spec("discord", search_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("discord.py package not found in environment")

    module = importlib.util.module_from_spec(spec)
    sys.modules["discord"] = module
    spec.loader.exec_module(module)
    return module


discord = cast(Any, _import_discord_api_module())
app_commands = cast(Any, discord.app_commands)


__all__ = ["discord", "app_commands"]

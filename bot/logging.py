from __future__ import annotations

import logging


def setup_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

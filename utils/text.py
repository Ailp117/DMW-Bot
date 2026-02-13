from __future__ import annotations

import re


_NANOMON_PATTERN = re.compile(r"\bnanomon\b")
_APPROVED_PATTERN = re.compile(r"\bapproved\b")


def normalize_list(text: str, *, max_items: int = 25) -> list[str]:
    parts = re.split(r"[,;\n]+", (text or "").strip())
    out: list[str] = []
    for part in parts:
        value = part.strip()
        if not value:
            continue
        if value in out:
            continue
        out.append(value)
        if len(out) >= max_items:
            break
    return out


def contains_nanomon_keyword(content: str) -> bool:
    return bool(_NANOMON_PATTERN.search((content or "").casefold()))


def contains_approved_keyword(content: str) -> bool:
    return bool(_APPROVED_PATTERN.search((content or "").casefold()))


def short_list(lines: list[str], *, limit: int = 50) -> str:
    if not lines:
        return "-"
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[:limit]) + f"\n... +{len(lines) - limit} more"

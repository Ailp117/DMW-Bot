from __future__ import annotations

from typing import Any


class RuntimeMixinBase:
    """Typing helper for dynamic runtime mixins.

    Runtime methods are spread across multiple mixins and composed in
    RewriteDiscordBot. For static type checkers, unknown cross-mixin attributes
    are treated as Any through __getattr__, avoiding false positives while
    preserving runtime behavior.
    """

    def __getattr__(self, _name: str) -> Any:
        raise AttributeError(_name)


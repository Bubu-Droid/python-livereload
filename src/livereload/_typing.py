"""
livereload._typing
~~~~~~~~~~~~~~~~~~

Typing helpers shared across the package.
"""

import sys
from collections.abc import Callable

# HACK: why are we using quotes while using cast(type, ...)
from typing import Literal, TypeAlias, TypeVar

# ask about the unused mypy and typing_extensions stuff

#: Seconds to wait before reloading, or ``'forever'`` to never reload.
Delay: TypeAlias = float | Literal["forever"] | None

#: Called with the path being checked; return True to ignore it.
IgnoreFunc: TypeAlias = Callable[[str], bool]

#: A watcher task: called with no arguments, or with the changed paths.
TaskFunc: TypeAlias = Callable[..., object]

if sys.version_info >= (3, 12):
    from typing import override
else:
    # Only reachable on Python 3.10 and 3.11.
    _F = TypeVar("_F", bound=Callable[..., object])  # pyright: ignore[reportUnreachable]

    def override(func: _F, /) -> _F:
        """No-op stand-in for :func:`typing.override` (Python 3.12+)."""
        return func


__all__ = ["Delay", "IgnoreFunc", "TaskFunc", "override"]

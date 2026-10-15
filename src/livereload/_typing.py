"""
livereload._typing
~~~~~~~~~~~~~~~~~~

Typing helpers shared across the package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Literal

    from typing_extensions import TypeAlias, override

    # These aliases are only visible to type checkers: ``X | Y`` cannot be
    # evaluated at runtime before Python 3.10. Import them inside an
    # ``if TYPE_CHECKING:`` block.

    #: Seconds to wait before reloading, or ``'forever'`` to never reload.
    Delay: TypeAlias = "float | Literal['forever'] | None"

    #: Called with the path being checked; return True to ignore it.
    IgnoreFunc: TypeAlias = Callable[[str], bool]

    #: A watcher task: called with no arguments, or with the changed paths.
    TaskFunc: TypeAlias = Callable[..., object]
else:
    # ``typing.override`` only exists on Python 3.12+. It has no runtime
    # effect beyond setting ``__override__``, so a no-op keeps it usable
    # on every supported version without a runtime dependency.
    def override(func):
        return func


__all__ = ["Delay", "IgnoreFunc", "TaskFunc", "override"]

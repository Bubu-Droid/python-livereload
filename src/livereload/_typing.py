"""
livereload._typing
~~~~~~~~~~~~~~~~~~

Typing helpers shared across the package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal, Union

if TYPE_CHECKING:
    from typing_extensions import override
else:
    # ``typing.override`` only exists on Python 3.12+. It has no runtime
    # effect beyond setting ``__override__``, so a no-op keeps it usable
    # on every supported version without a runtime dependency.
    def override(func):
        return func


#: Seconds to wait before reloading, or ``'forever'`` to never reload.
Delay = Union[float, Literal["forever"], None]

#: Called with the path being checked; return True to ignore it.
IgnoreFunc = Callable[[str], bool]

#: A watcher task: called with no arguments, or with the changed paths.
TaskFunc = Callable[..., object]

__all__ = ["Delay", "IgnoreFunc", "TaskFunc", "override"]

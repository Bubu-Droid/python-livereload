# Minimal stubs for the parts of pyinotify that livereload uses.
# pyinotify ships no type information; it is an optional dependency.

from collections.abc import Callable

from tornado.ioloop import IOLoop

IN_CREATE: int
IN_DELETE: int
IN_MODIFY: int

class Event: ...

class WatchManager:
    def add_watch(
        self,
        path: str,
        mask: int,
        proc_fun: Callable[[Event], object] | None = None,
        rec: bool = False,
        auto_add: bool = False,
        do_glob: bool = False,
        quiet: bool = True,
    ) -> dict[str, int]: ...

class TornadoAsyncNotifier:
    def __init__(
        self,
        watch_manager: WatchManager,
        ioloop: IOLoop,
        callback: Callable[[TornadoAsyncNotifier], object] | None = None,
        default_proc_fun: Callable[[Event], object] | None = None,
    ) -> None: ...

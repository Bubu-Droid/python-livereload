"""
livereload.handlers
~~~~~~~~~~~~~~~~~~~

HTTP and WebSocket handlers for livereload.

:copyright: (c) 2013 by Hsiaoming Yang
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import stat
import time
from typing import ClassVar, cast

from tornado import escape, ioloop, web
from tornado.log import gen_log
from tornado.websocket import WebSocketHandler

from livereload._typing import override
from livereload.watcher import Watcher

logger = logging.getLogger("livereload")


class LiveReloadHandler(WebSocketHandler):
    DEFAULT_RELOAD_TIME: ClassVar[int] = 3
    waiters: ClassVar[set[LiveReloadHandler]] = set()
    watcher: ClassVar[Watcher | None] = None
    live_css: ClassVar[bool | None] = None
    _last_reload_time: ClassVar[float | None] = None

    def allow_draft76(self) -> bool:
        return True

    @override
    def check_origin(self, origin: str) -> bool:
        return True

    @override
    def on_close(self) -> None:
        if self in LiveReloadHandler.waiters:
            LiveReloadHandler.waiters.remove(self)

    def send_message(self, message: dict[str, object] | str) -> None:
        if isinstance(message, dict):
            message = escape.json_encode(message)

        try:
            _ = self.write_message(message)
        except Exception:
            logger.exception("Error sending message")

    @classmethod
    def start_tasks(cls) -> None:
        if cls._last_reload_time:
            return

        assert cls.watcher is not None

        if not cls.watcher._tasks:  # pyright: ignore[reportPrivateUsage]
            logger.info("Watch current working directory")
            cls.watcher.watch(os.getcwd())

        cls._last_reload_time = time.time()
        logger.info("Start watching changes")
        if not cls.watcher.start(cls.poll_tasks):
            logger.info("Start detecting changes")
            ioloop.PeriodicCallback(cls.poll_tasks, 800).start()

    @classmethod
    def poll_tasks(cls) -> None:
        assert cls.watcher is not None
        assert cls._last_reload_time is not None
        filepath, delay = cls.watcher.examine()
        if not filepath or delay == "forever" or not cls.waiters:
            return
        reload_time: float = LiveReloadHandler.DEFAULT_RELOAD_TIME

        if delay:
            reload_time = max(3 - delay, 1)
        if filepath == "__livereload__":
            reload_time = 0

        if time.time() - cls._last_reload_time < reload_time:
            # if you changed lot of files in one time
            # it will refresh too many times
            logger.info("Ignore: %s", filepath)
            return
        if delay:
            loop = ioloop.IOLoop.current()
            # tornado types the callback as a bare ``Callable``
            _ = loop.call_later(delay, cls.reload_waiters)  # pyright: ignore[reportUnknownMemberType]
        else:
            cls.reload_waiters()

    @classmethod
    def reload_waiters(cls, path: str | None = None) -> None:
        assert cls.watcher is not None
        logger.info(
            "Reload %s waiters: %s",
            len(cls.waiters),
            cls.watcher.filepath,
        )

        if path is None:
            path = cls.watcher.filepath or "*"

        msg = {
            "command": "reload",
            "path": path,
            "liveCSS": cls.live_css,
            "liveImg": True,
        }

        cls._last_reload_time = time.time()
        for waiter in cls.waiters.copy():
            try:
                _ = waiter.write_message(msg)
            except Exception:
                logger.exception("Error sending message")
                cls.waiters.remove(waiter)

    @override
    def on_message(self, message: str | bytes) -> None:
        """Handshake with livereload.js

        1. client send 'hello'
        2. server reply 'hello'
        3. client send 'info'
        """
        data = cast(dict[str, object], escape.json_decode(message))
        if data.get("command") == "hello":
            handshake: dict[str, object] = {
                "command": "hello",
                "protocols": [
                    "http://livereload.com/protocols/official-7",
                ],
                "serverName": "livereload-tornado",
            }
            self.send_message(handshake)

        if data.get("command") == "info" and "url" in data:
            logger.info("Browser Connected: %s", data["url"])
            LiveReloadHandler.waiters.add(self)


class MtimeStaticFileHandler(web.StaticFileHandler):
    _static_mtimes: ClassVar[dict[str, datetime.datetime | None]] = {}

    @classmethod
    def get_content_modified_time(cls, abspath: str) -> datetime.datetime:
        """Returns the time that ``abspath`` was last modified.

        May be overridden in subclasses.  Should return a `~datetime.datetime`
        object or None.
        """
        stat_result = os.stat(abspath)
        modified = datetime.datetime.fromtimestamp(
            stat_result[stat.ST_MTIME], datetime.timezone.utc
        )
        # Naive UTC, as ``utcfromtimestamp`` used to return.
        return modified.replace(tzinfo=None)

    @classmethod
    @override
    def get_content_version(cls, abspath: str) -> str:
        """Returns a version string for the resource at the given path.

        This class method may be overridden by subclasses.  The
        default implementation is a hash of the file's contents.

        .. versionadded:: 3.1
        """
        data = cls.get_content(abspath)
        hasher = hashlib.md5()

        mtime_data = format(
            cls.get_content_modified_time(abspath), "%Y-%m-%d %H:%M:%S"
        )

        hasher.update(mtime_data.encode())

        if isinstance(data, bytes):
            hasher.update(data)
        else:
            for chunk in data:
                hasher.update(chunk)
        return hasher.hexdigest()

    @classmethod
    @override
    def _get_cached_version(cls, abs_path: str) -> str | None:
        def _load_version(
            abs_path: str,
        ) -> tuple[datetime.datetime | None, str | None]:
            try:
                hsh = cls.get_content_version(abs_path)
                mtm = cls.get_content_modified_time(abs_path)

                return mtm, hsh
            except OSError:
                gen_log.error("Could not open static file %r", abs_path)
                return None, None

        with cls._lock:
            hashes = cls._static_hashes
            mtimes = cls._static_mtimes

            if abs_path not in hashes:
                mtm, hsh = _load_version(abs_path)

                hashes[abs_path] = hsh
                mtimes[abs_path] = mtm
            else:
                hsh = hashes.get(abs_path)
                mtm = mtimes.get(abs_path)

                if mtm != cls.get_content_modified_time(abs_path):
                    mtm, hsh = _load_version(abs_path)

                    hashes[abs_path] = hsh
                    mtimes[abs_path] = mtm

            if hsh:
                return hsh
        return None


class LiveReloadJSHandler(web.RequestHandler):
    @override
    def get(self) -> None:
        self.set_header("Content-Type", "application/javascript")
        root = os.path.abspath(os.path.dirname(__file__))
        js_file = os.path.join(root, "vendors/livereload.js")
        with open(js_file, "rb") as f:
            # tornado types ``write`` with a bare ``dict``
            self.write(f.read())  # pyright: ignore[reportUnknownMemberType]


class ForceReloadHandler(web.RequestHandler):
    @override
    def get(self) -> None:
        path = self.get_argument("path", default=None) or "*"
        LiveReloadHandler.reload_waiters(path)
        self.write("ok")  # pyright: ignore[reportUnknownMemberType]


class StaticFileHandler(MtimeStaticFileHandler):
    @override
    def should_return_304(self) -> bool:
        return False

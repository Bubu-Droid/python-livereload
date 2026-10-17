"""
livereload.server
~~~~~~~~~~~~~~~~~

WSGI app server for livereload.

:copyright: (c) 2013 - 2015 by Hsiaoming Yang
:license: BSD, see LICENSE for more details.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import shlex

# import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING, ClassVar, cast

from tornado import escape, httputil, web
from tornado.autoreload import add_reload_hook
from tornado.ioloop import IOLoop
from tornado.log import LogFormatter
from tornado.wsgi import WSGIContainer

from livereload._typing import override
from livereload.handlers import (
    ForceReloadHandler,
    LiveReloadHandler,
    LiveReloadJSHandler,
    StaticFileHandler,
)
from livereload.watcher import get_watcher_class

if TYPE_CHECKING:
    from types import TracebackType

    from _typeshed.wsgi import WSGIApplication
    from tornado.routing import _RuleList  # pyright: ignore[reportPrivateUsage]

    from livereload._typing import Delay, IgnoreFunc, TaskFunc
    from livereload.watcher import Watcher

# FIX:
# Event loop policies are deprecated in 3.14 and removed in 3.16; tornado
# supports the default Windows proactor loop on its own since 6.1.
# if sys.platform == "win32" and sys.version_info < (3, 14):
#     import asyncio
#     asyncio.set_event_loop_policy(
#         asyncio.WindowsSelectorEventLoopPolicy()
#     )

logger = logging.getLogger("livereload")

HEAD_END_RE = re.compile(rb"</head>", re.IGNORECASE)


def inject_script_at_head(content: bytes, script: bytes) -> bytes:
    """Inject script before closing </head> tag, case-insensitive."""
    return HEAD_END_RE.sub(
        lambda match: script + match.group(0), content, count=1
    )


def set_header(
    fn: Callable[..., None], name: str, value: str
) -> Callable[..., None]:
    """Helper Function to Add HTTP headers to the server"""

    def set_default_headers(
        self: web.RequestHandler, *args: object, **kwargs: object
    ) -> None:
        fn(self, *args, **kwargs)
        self.set_header(name, value)

    return set_default_headers


def shell(
    cmd: str | list[str] | tuple[str, ...],
    output: str | None = None,
    mode: str = "w",
    cwd: str | None = None,
    shell: bool = False,
) -> Callable[[], OSError | str | None]:
    """Execute a shell command.

    You can add a shell command::

        server.watch(
            'style.less', shell('lessc style.less', output='style.css')
        )

    :param cmd: a shell command, string or list
    :param output: output stdout to the given file
    :param mode: only works with output, mode ``w`` means write,
                 mode ``a`` means append
    :param cwd: set working directory before command is executed.
    :param shell: if true, on Unix the executable argument specifies a
                  replacement shell for the default ``/bin/sh``.
    """
    if not output:
        output = os.devnull
    else:
        folder = os.path.dirname(output)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)

    if not isinstance(cmd, (list, tuple)) and not shell:
        cmd = shlex.split(cmd)

    def run_shell() -> OSError | str | None:
        try:
            p = Popen(
                cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=cwd, shell=shell
            )
        except OSError as e:
            logger.error(e)
            if e.errno == errno.ENOENT:  # file (command) not found
                logger.error("maybe you haven't installed %s", cmd[0])
            return e
        out, err = p.communicate()
        #: stdout is bytes, decode for python3
        stdout = out.decode()
        stderr = err.decode()
        if stderr:
            logger.error(stderr)
            return stderr
        with open(output, mode) as f:
            _ = f.write(stdout)
        return None

    return run_shell


class LiveScriptInjector(web.OutputTransform):
    script: ClassVar[bytes] = b""

    def __init__(self, request: httputil.HTTPServerRequest) -> None:
        super().__init__(request)

    @override
    def transform_first_chunk(
        self,
        status_code: int,
        headers: httputil.HTTPHeaders,
        chunk: bytes,
        finishing: bool,
    ) -> tuple[int, httputil.HTTPHeaders, bytes]:
        is_html = "html" in headers.get("Content-Type", "")
        if is_html and HEAD_END_RE.search(chunk):
            chunk = inject_script_at_head(chunk, self.script)
            if "Content-Length" in headers:
                length = int(headers["Content-Length"]) + len(self.script)
                headers["Content-Length"] = str(length)
        return status_code, headers, chunk


class LiveScriptContainer(WSGIContainer):
    def __init__(self, wsgi_app: WSGIApplication, script: bytes = b"") -> None:
        super().__init__(wsgi_app)
        self.wsgi_app: WSGIApplication = wsgi_app
        self.script: bytes = script

    @override
    def __call__(self, request: httputil.HTTPServerRequest) -> None:
        # (status, headers) passed to start_response by the WSGI app
        started: list[tuple[str, list[tuple[str, str]]]] = []
        response: list[bytes] = []

        def start_response(
            status_line: str,
            response_headers: list[tuple[str, str]],
            _exc_info: (
                tuple[type[BaseException], BaseException, TracebackType]
                | tuple[None, None, None]
                | None
            ) = None,
        ) -> Callable[[bytes], object]:
            started.append((status_line, response_headers))
            return response.append

        app_response = self.wsgi_app(
            WSGIContainer(self.wsgi_app).environ(request), start_response
        )
        try:
            response.extend(app_response)
            body = b"".join(response)
        finally:
            close = cast(
                Callable[[], object] | None,
                getattr(app_response, "close", None),
            )
            if close is not None:
                _ = close()
        if not started:
            raise RuntimeError("WSGI app did not call start_response")

        status, headers = started[-1]
        code, reason = status.split(" ", 1)
        status_code = int(code)
        header_set = {k.lower() for (k, _) in headers}
        body = escape.utf8(body)

        if HEAD_END_RE.search(body):
            body = inject_script_at_head(body, self.script)

        if status_code != 304:
            if "content-type" not in header_set:
                headers.append(
                    ("Content-Type", "application/octet-stream; charset=UTF-8")
                )
            if "content-length" not in header_set:
                headers.append(("Content-Length", str(len(body))))

        if "server" not in header_set:
            headers.append(("Server", "LiveServer"))

        start_line = httputil.ResponseStartLine("HTTP/1.1", status_code, reason)
        header_obj = httputil.HTTPHeaders()
        for key, value in headers:
            if key.lower() == "content-length":
                value = str(len(body))
            header_obj.add(key, value)
        assert request.connection is not None
        _ = request.connection.write_headers(start_line, header_obj, chunk=body)
        request.connection.finish()
        self._log(status_code, request)


class Server:
    """Livereload server interface.

    Initialize a server and watch file changes::

        server = Server(wsgi_app)
        server.serve()

    :param app: a WSGI application instance
    :param watcher: A Watcher instance, you don't have to initialize
                    it by yourself. Under Linux, you will want to install
                    pyinotify and use INotifyWatcher() to avoid wasted
                    CPU usage.
    """

    def __init__(
        self,
        app: WSGIApplication | None = None,
        watcher: Watcher | None = None,
    ) -> None:
        self.root: str | None = None
        self.default_filename: str = "index.html"

        self.app: WSGIApplication | None = app
        if not watcher:
            watcher_cls = get_watcher_class()
            watcher = watcher_cls()
        self.watcher: Watcher = watcher
        self.static_file_handler: type[StaticFileHandler] = StaticFileHandler

    def setHeader(self, name: str, value: str) -> None:
        """Add or override HTTP headers at the at the beginning of the
           request.

        Once you have initialized a server, you can add one or more
        headers before starting the server::

            server.setHeader('Access-Control-Allow-Origin', '*')
            server.setHeader('Access-Control-Allow-Methods', '*')
            server.serve()

        :param name: The name of the header field to be defined.
        :param value: The value of the header field to be defined.
        """
        StaticFileHandler.set_default_headers = set_header(
            StaticFileHandler.set_default_headers, name, value
        )
        self.static_file_handler = StaticFileHandler

    def watch(
        self,
        filepath: str,
        func: str | TaskFunc | None = None,
        delay: Delay = None,
        ignore: IgnoreFunc | None = None,
    ) -> None:
        """Add the given filepath for watcher list.

        Once you have initialized a server, watch file changes before
        serve the server::

            server.watch('static/*.stylus', 'make static')
            def alert():
                print('foo')
            server.watch('foo.txt', alert)
            server.serve()

        :param filepath: files to be watched, it can be a filepath,
                         a directory, or a glob pattern
        :param func: the function to be called, it can be a string of
                     shell command, or any callable object without
                     parameters
        :param delay: Delay sending the reload message. Use 'forever' to
                      not send it. This is useful to compile sass files to
                      css, but reload on changed css files then only.
        :param ignore: A function return True to ignore a certain pattern of
                       filepath.
        """
        if isinstance(func, str):
            cmd = func
            func = shell(func)
            func.__name__ = f"shell: {cmd}"

        self.watcher.watch(filepath, func, delay, ignore=ignore)

    def application(
        self,
        port: int,
        host: str,
        liveport: int | None = None,
        debug: bool | None = None,
        live_css: bool = True,
    ) -> None:
        LiveReloadHandler.watcher = self.watcher
        LiveReloadHandler.live_css = live_css
        if debug is None and self.app:
            debug = True

        live_handlers: _RuleList = [
            (r"/livereload", LiveReloadHandler),
            (r"/forcereload", ForceReloadHandler),
            (r"/livereload.js", LiveReloadJSHandler),
        ]

        # The livereload.js snippet.
        # Uses JavaScript to dynamically inject the client's hostname.
        # This allows for serving on 0.0.0.0.
        script_template = (
            '<script type="text/javascript">(function(){'
            'var s=document.createElement("script");'
            "var port=%s;"
            's.src="//"+window.location.hostname+":"+port'
            '+ "/livereload.js?port=" + port;'
            "document.head.appendChild(s);"
            "})();</script>"
        )
        if liveport:
            live_script = escape.utf8(script_template % liveport)
        else:
            live_script = escape.utf8(
                script_template
                % (
                    "(window.location.port || "
                    "(window.location.protocol == 'https:' ? 443: 80))"
                )
            )

        web_handlers = self.get_web_handlers(live_script)

        class ConfiguredTransform(LiveScriptInjector):
            script: ClassVar[bytes] = live_script

        if not liveport:
            handlers: _RuleList = [*live_handlers, *web_handlers]
            app = web.Application(
                handlers=handlers, debug=debug, transforms=[ConfiguredTransform]
            )
            _ = app.listen(port, address=host)
        else:
            app = web.Application(
                handlers=web_handlers,
                debug=debug,
                transforms=[ConfiguredTransform],
            )
            _ = app.listen(port, address=host)
            live = web.Application(handlers=live_handlers, debug=False)
            _ = live.listen(liveport, address=host)

    def get_web_handlers(self, script: bytes) -> _RuleList:
        if self.app:
            fallback = LiveScriptContainer(self.app, script)
            return [(r".*", web.FallbackHandler, {"fallback": fallback})]
        return [
            (
                r"/(.*)",
                self.static_file_handler,
                {
                    "path": self.root or ".",
                    "default_filename": self.default_filename,
                },
            ),
        ]

    def serve(
        self,
        port: int = 5500,
        liveport: int | None = None,
        host: str | None = None,
        root: str | None = None,
        debug: bool | None = None,
        open_url: bool = False,
        restart_delay: float = 2,
        open_url_delay: float | None = None,
        live_css: bool = True,
        default_filename: str = "index.html",
    ) -> None:
        """Start serve the server with the given port.

        :param port: serve on this port, default is 5500
        :param liveport: live reload on this port
        :param host: serve on this hostname, default is 127.0.0.1
        :param root: serve static on this root directory
        :param debug: set debug mode, which autoreloads the app on code changes
                      via Tornado (and causes polling). Defaults to True when
                      ``self.app`` is set, otherwise False.
        :param open_url_delay: open webbrowser after the delay seconds
        :param live_css: whether to use live css or force reload on css.
                         Defaults to True
        :param default_filename: launch this file from the selected root on startup
        """
        host = host or "127.0.0.1"
        if root is not None:
            self.root = root

        self._setup_logging()
        logger.info(f"Serving on http://{host}:{port}")

        self.default_filename = default_filename

        self.application(
            port, host, liveport=liveport, debug=debug, live_css=live_css
        )

        # Async open web browser after 5 sec timeout
        if open_url:
            logger.error("Use `open_url_delay` instead of `open_url`")
        if open_url_delay is not None:

            def opener() -> None:
                assert open_url_delay is not None
                time.sleep(open_url_delay)
                _ = webbrowser.open(f"http://{host}:{port}")

            threading.Thread(target=opener).start()

        try:
            self.watcher._changes.append(("__livereload__", restart_delay))  # pyright: ignore[reportPrivateUsage]
            LiveReloadHandler.start_tasks()
            # When autoreload is triggered, initiate a shutdown of the IOLoop
            add_reload_hook(lambda: IOLoop.instance().stop())
            # The call to start() does not return until the IOLoop is stopped.
            IOLoop.instance().start()
            # Once the IOLoop is stopped, the IOLoop can be closed to free resources
            IOLoop.current().close(all_fds=True)
        except KeyboardInterrupt:
            logger.info("Shutting down...")

    def _setup_logging(self) -> None:
        logger.setLevel(logging.INFO)

        channel = logging.StreamHandler()
        channel.setFormatter(LogFormatter())
        logger.addHandler(channel)

        # need a tornado logging handler to prevent IOLoop._setup_logging
        logging.getLogger("tornado").addHandler(channel)

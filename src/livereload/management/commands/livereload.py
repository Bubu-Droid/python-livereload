from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, cast

from django.core.management.base import BaseCommand, CommandError
from django.core.management.commands.runserver import naiveip_re
from django.core.servers.basehttp import get_internal_wsgi_application

from livereload import Server
from livereload._typing import override

if TYPE_CHECKING:
    from django.core.management.base import CommandParser


class Command(BaseCommand):
    help: str = "Runs the development server with livereload enabled."

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "addrport",
            nargs="?",
            default="127.0.0.1:8000",
            help=(
                "host and optional port the django server should "
                "listen on (default: 127.0.0.1:8000)"
            ),
        )
        parser.add_argument(
            "-l",
            "--liveport",
            type=int,
            default=35729,
            help=("port the livereload server should listen on (default: 35729)"),
        )

    @override
    def handle(self, *args: object, **options: object) -> None:
        del args  # the command takes no positional labels
        addrport = cast("str", options["addrport"])
        liveport = cast("int", options["liveport"])
        m = re.match(naiveip_re, addrport)
        if m is None:
            raise CommandError(
                f'"{addrport}" is not a valid port number or address:port pair.'
            )
        addr, _ipv4, _ipv6, _fqdn, port = m.groups()
        if not port.isdigit():
            raise CommandError(f"{port!r} is not a valid port number.")

        if addr:
            if _ipv6:
                raise CommandError("IPv6 addresses are currently not supported.")

        application = get_internal_wsgi_application()
        server = Server(application)

        for file in os.listdir("."):
            if file[0] != "." and file[:2] != "__" and os.path.isdir(file):
                server.watch(file)

        server.serve(host=addr, port=int(port), liveport=liveport)

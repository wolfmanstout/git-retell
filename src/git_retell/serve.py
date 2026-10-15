"""Serve a web page over HTTP so another device, such as a phone, can open it.

The page answers only under a random path, so the URL itself is the
credential: anyone who finds the port, or a tunnel's public hostname, gets
404s without it. Tunnels and authentication are left to tools built for them
(Tailscale, ngrok); the tool only listens.
"""

import secrets
import socket
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import quote

import click

from .web import page

# Hosts that listen on every interface and so can't be dialed as written.
WILDCARDS = {"", "0.0.0.0", "::"}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int, path: Path, data: dict):
        if ":" in host:
            self.address_family = socket.AF_INET6
        self.token = secrets.token_urlsafe(16)
        self.filename = path.name
        # Downloads get the file as written; only the served copy shows the
        # Download button, since a saved file has nothing to download from.
        self.download = path.read_bytes()
        self.page = page({**data, "download": path.name}).encode()
        super().__init__((host, port), Handler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        if host in WILDCARDS:
            host = socket.gethostname()
        elif ":" in str(host):
            host = f"[{host}]"
        return f"http://{host}:{port}/{self.token}/"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(body=True)

    def do_HEAD(self):
        self.respond(body=False)

    def respond(self, body: bool):
        server = cast(Server, self.server)
        root = f"/{server.token}/"
        path = self.path.split("?", 1)[0]
        if path == root.rstrip("/"):
            # The page's relative Download link needs the trailing slash.
            self.send_response(HTTPStatus.PERMANENT_REDIRECT)
            self.send_header("Location", root)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == root:
            content, disposition = server.page, None
        elif path == root + "download":
            name = quote(server.filename)
            content = server.download
            disposition = f"attachment; filename*=UTF-8''{name}"
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        # Keep the token out of Referer headers sent to linked sites.
        self.send_header("Referrer-Policy", "no-referrer")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        if body:
            self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        """Stay quiet; the printed URL is the only output agents need."""


def serve(path: Path, data: dict, host: str, port: int, open_browser: bool) -> None:
    """Serve the page at path until interrupted."""
    try:
        server = Server(host, port, path, data)
    except OSError as error:
        raise click.ClickException(
            f"Cannot listen on {host}:{port}: {error.strerror or error}"
        ) from error
    with server:
        click.echo(f"Serving {server.url}")
        click.echo("Press Ctrl-C to stop.")
        if open_browser:
            webbrowser.open(server.url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

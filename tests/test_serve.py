import threading
import urllib.error
import urllib.request

import pytest
from click.testing import CliRunner

from git_retell import web
from git_retell.cli import cli
from git_retell.serve import Server

from .helpers import commit, example, refresh


@pytest.fixture
def server(repo, tmp_path):
    retelling, author = example(repo, tmp_path)
    (author / "code.txt").write_text("after\n")
    commit(author, "Change the code")
    path, data = web.web(refresh(retelling), tmp_path / "demo.html")
    server = Server("127.0.0.1", 0, path, data)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def fetch(url):
    with urllib.request.urlopen(url) as response:
        return response.headers, response.read()


def status(url):
    try:
        with urllib.request.urlopen(url) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_page_is_served_only_under_the_token(server):
    headers, body = fetch(server.url)
    assert headers["Referrer-Policy"] == "no-referrer"
    assert b'"download":"demo.html"' in body
    origin = server.url.removesuffix(f"{server.token}/")
    assert status(origin) == 404
    assert status(origin + "download") == 404
    assert status(origin + server.token[:-1] + "/") == 404


def test_url_without_trailing_slash_redirects(server):
    # urllib follows the redirect, so the page arrives at the slash URL.
    with urllib.request.urlopen(server.url.rstrip("/")) as response:
        assert response.url == server.url


def test_download_is_the_written_file(server, tmp_path):
    headers, body = fetch(server.url + "download")
    assert headers["Content-Disposition"] == "attachment; filename*=UTF-8''demo.html"
    assert body == (tmp_path / "demo.html").read_bytes()
    assert b'"download":' not in body


def test_host_and_port_require_serve(repo, tmp_path):
    example(repo, tmp_path)
    result = CliRunner().invoke(cli, ["web", "demo", "--no-open", "--port", "8000"])
    assert result.exit_code == 2
    assert "--host and --port require --serve" in result.output

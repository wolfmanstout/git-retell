import os

import pytest

from git_retell.git import git

from .helpers import commit


@pytest.fixture(autouse=True)
def hermetic_git(tmp_path_factory, monkeypatch):
    """Isolate every git command from the machine running the tests.

    Inherited GIT_* variables are dropped, and a temporary HOME holds the only
    global config, so the user's ~/.gitconfig and ~/.config/git ignore and
    attributes files never apply. The identity lives in that config rather
    than GIT_AUTHOR_* variables, so the code's own git -c identity still
    wins. Only local file transports are allowed, so a test can never reach
    the network.
    """
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    home = tmp_path_factory.mktemp("home")
    (home / ".gitconfig").write_text(
        "[user]\n"
        "\tname = Retell Test\n"
        "\temail = retell@example.invalid\n"
        "\tuseConfigOnly = true\n"
        "[init]\n"
        "\tdefaultBranch = main\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    (path / "code.txt").write_text("before\n")
    commit(path, "Before")
    monkeypatch.chdir(path)
    return path

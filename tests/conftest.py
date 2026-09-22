import os

import pytest

from git_retell.git import git

from .helpers import commit


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Retell Test")
    git(path, "config", "user.email", "retell@example.invalid")
    (path / "code.txt").write_text("before\n")
    commit(path, "Before")
    monkeypatch.chdir(path)
    return path

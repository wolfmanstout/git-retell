"""Shared helpers for authoring test histories in real Git repositories."""

from git_retell.git import git, resolve
from git_retell.history import History, start


def commit(path, message):
    git(path, "add", "--all")
    git(path, "commit", "--allow-empty", "-m", message)
    return resolve(path, "HEAD")


def example(repo, tmp_path, target="after\n", budget=60):
    base = resolve(repo, "HEAD")
    (repo / "code.txt").write_text(target)
    head = commit(repo, "Real change")
    path = tmp_path / "author"
    history = start(repo, "demo", base, head, path, budget)
    return history, path


def refresh(history):
    return History.load(history.repo, history.name)

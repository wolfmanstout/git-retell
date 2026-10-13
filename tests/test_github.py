import json
import os
import tempfile
from pathlib import Path

from click.testing import CliRunner

from git_retell.cli import cli
from git_retell.git import git, resolve
from git_retell.github import remote_project

from .helpers import commit


def fake_pull_request(repo, tmp_path, monkeypatch):
    """Publish a PR in an upstream repo that the local clone has not fetched.

    A fake gh reports it, and insteadOf points its GitHub URL at the upstream.
    """
    upstream = tmp_path / "upstream"
    git(tmp_path, "clone", "--quiet", str(repo), str(upstream))
    git(upstream, "switch", "--quiet", "-c", "feature")
    (upstream / "code.txt").write_text("feature\n")
    head = commit(upstream, "Feature")
    git(upstream, "update-ref", "refs/pull/7/head", head)
    git(upstream, "switch", "--quiet", "main")
    (upstream / "other.txt").write_text("moved on\n")
    main = commit(upstream, "Main moved on")
    git(repo, "config", f"url.{upstream}.insteadOf", "https://github.com/o/r.git")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    info = {
        "number": 7,
        "title": "Add a feature",
        "url": "https://github.com/O/R/pull/7",
        "baseRefName": "main",
        "baseRefOid": main,
        "headRefOid": head,
    }
    (bin_dir / "info.json").write_text(json.dumps(info))
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\ncat "{bin_dir / "info.json"}"\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return head


def test_start_pr_fetches_and_pins_merge_base_and_head(repo, tmp_path, monkeypatch):
    base = resolve(repo, "HEAD")
    head = fake_pull_request(repo, tmp_path, monkeypatch)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--pr", "7"])
    assert result.exit_code == 0, result.output
    assert "Pull request #7: Add a feature" in result.output
    assert resolve(repo, "refs/retell/pr-7/base") == base
    assert resolve(repo, "refs/retell/pr-7/target") == head
    assert resolve(repo, "main") == base
    path = result.output.split("Author in: ")[1].splitlines()[0]
    assert Path(path).parent == tmp_path.resolve() and Path(path).is_dir()
    assert Path(path).name.startswith("git-retell-pr-7-")
    result = runner.invoke(cli, ["start", "--pr", "7"])
    assert result.exit_code == 1 and "already exists" in result.output
    result = runner.invoke(cli, ["start", "--pr", "7", "--from", "HEAD"])
    assert result.exit_code == 2 and "--pr sets both endpoints" in result.output
    result = runner.invoke(cli, ["configure", "pr-7", "--pr", "7"])
    assert result.exit_code == 0 and f"Target: {head}" in result.output


def test_show_pr_lists_its_commits(repo, tmp_path, monkeypatch):
    fake_pull_request(repo, tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["show", "--pr", "7", "--all"])
    assert result.exit_code == 0, result.output
    assert "Feature" in result.output and "+feature" in result.output
    assert "Main moved on" not in result.output


def test_start_without_name_needs_pr(repo, tmp_path):
    result = CliRunner().invoke(cli, ["start", "--from", "HEAD"])
    assert result.exit_code == 2 and "--pr" in result.output


def test_remote_project_normalizes_urls():
    for url in (
        "git@github.com:O/R.git",
        "https://github.com/o/r",
        "https://user@github.com/o/r.git",
        "ssh://git@github.com/o/r.git",
        "ssh://git@github.com:22/o/r",
    ):
        assert remote_project(url) == "github.com/o/r", url

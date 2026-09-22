import json
import sys

from click.testing import CliRunner

from git_retell import checks
from git_retell.cli import cli
from git_retell.git import git
from git_retell.history import inspect

from .helpers import commit, example, refresh


def test_checks_report_failures_and_clean_worktrees(repo, tmp_path):
    history, path = example(repo, tmp_path)
    (path / "code.txt").write_text("naive\n")
    commit(path, "Intermediate")
    (path / "code.txt").write_text("after\n")
    commit(path, "Final")
    before = git(repo, "worktree", "list", "--porcelain")
    command = (
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('code.txt').read_text() == 'after\\n'",
    )
    result = CliRunner().invoke(
        cli, ["check", "demo", "--timeout", "2", "--", *command]
    )
    assert result.exit_code == 1
    assert [r["passed"] for r in json.loads(result.output)] == [False, True]
    assert git(repo, "worktree", "list", "--porcelain") == before
    assert inspect(refresh(history))["valid"]


def test_check_timeout_and_missing_command(repo):
    result = checks.run_check(
        repo, (sys.executable, "-c", "import time; time.sleep(10)"), 0.02
    )
    assert result["timed_out"] and not result["passed"]
    assert not checks.run_check(repo, ("/nonexistent-retell-command",), 1)["passed"]

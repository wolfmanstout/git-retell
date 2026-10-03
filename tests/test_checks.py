import json
import sys

from click.testing import CliRunner

from git_retell import checks
from git_retell.cli import cli
from git_retell.git import git
from git_retell.retelling import inspect

from .helpers import commit, example, refresh


def test_steps_report_failures_and_clean_worktrees(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
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
    runner = CliRunner()
    result = runner.invoke(
        cli, ["test", "demo", "--timeout", "2", "--json", "--", *command]
    )
    assert result.exit_code == 1
    assert [r["passed"] for r in json.loads(result.output)] == [False, True]
    assert git(repo, "worktree", "list", "--porcelain") == before
    result = runner.invoke(cli, ["test", "demo", "--", *command])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert "fail (1)" in lines[0] and "Intermediate" in lines[0]
    assert any("AssertionError" in line for line in lines)
    assert "pass" in result.output and "1 of 2 steps passed." in result.output
    assert git(repo, "worktree", "list", "--porcelain") == before
    assert inspect(refresh(retelling))["valid"]


def test_command_timeout_and_missing_command(repo):
    result = checks.run_check(
        repo, (sys.executable, "-c", "import time; time.sleep(10)"), 0.02
    )
    assert result["timed_out"] and not result["passed"]
    assert not checks.run_check(repo, ("/nonexistent-retell-command",), 1)["passed"]

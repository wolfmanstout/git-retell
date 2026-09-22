import json

from click.testing import CliRunner

from git_retell.cli import cli

from .helpers import commit, example, refresh


def test_help_and_version():
    runner = CliRunner()
    assert runner.invoke(cli, ["--version"]).exit_code == 0
    help_text = runner.invoke(cli, ["--help"]).output
    assert "SYNTHETIC" in help_text and "EXACTLY" in help_text


def test_start_rejects_collisions_without_changing_history(repo, tmp_path):
    history, path = example(repo, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "start",
            "demo",
            "--base",
            "HEAD",
            "--target",
            "HEAD",
            "--worktree",
            str(path),
        ],
    )
    assert result.exit_code != 0 and "already exists" in result.output
    assert refresh(history) == history
    result = runner.invoke(
        cli,
        [
            "start",
            "../bad",
            "--base",
            "HEAD",
            "--target",
            "HEAD",
            "--worktree",
            str(tmp_path / "bad"),
        ],
    )
    assert result.exit_code != 0


def test_cli_validate_show_and_nonterminal_view(repo, tmp_path):
    _history, path = example(repo, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "demo", "--json"])
    assert result.exit_code == 1 and not json.loads(result.output)["valid"]
    (path / "code.txt").write_text("after\n")
    commit(path, "Explain the change")
    assert runner.invoke(cli, ["validate", "demo"]).exit_code == 0
    result = runner.invoke(cli, ["show", "demo", "--all"])
    assert "SYNTHETIC" in result.output and "Explain the change" in result.output
    assert "-before" in result.output and "+after" in result.output
    assert runner.invoke(cli, ["show", "demo", "--step", "2"]).exit_code == 1
    assert runner.invoke(cli, ["view", "demo"]).exit_code == 1

import json

from click.testing import CliRunner

from git_retell.cli import cli
from git_retell.git import git, resolve
from git_retell.retelling import Retelling, start

from .helpers import commit, example, refresh


def test_help_and_version():
    runner = CliRunner()
    assert runner.invoke(cli, ["--version"]).exit_code == 0
    help_text = runner.invoke(cli, ["--help"]).output
    assert "SYNTHETIC" in help_text and "EXACTLY" in help_text


def test_start_rejects_collisions_without_changing_retelling(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
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
    assert refresh(retelling) == retelling
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
    _retelling, path = example(repo, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "demo", "--json"])
    assert result.exit_code == 1 and not json.loads(result.output)["valid"]
    (path / "code.txt").write_text("after\n")
    commit(path, "Explain the change")
    assert runner.invoke(cli, ["validate", "demo"]).exit_code == 0
    result = runner.invoke(cli, ["show", "demo", "--all"])
    assert "SYNTHETIC" in result.output and "Explain the change" in result.output
    assert "-before" in result.output and "+after" in result.output
    assert "[q] quit" not in result.output and "q:quit" not in result.output
    assert runner.invoke(cli, ["show", "demo", "--step", "2"]).exit_code == 1
    assert runner.invoke(cli, ["view", "demo"]).exit_code == 1


def test_list_and_delete_retellings(repo, tmp_path):

    runner = CliRunner()
    assert json.loads(runner.invoke(cli, ["list", "--json"]).output) == []
    assert "No retellings" in runner.invoke(cli, ["list"]).output
    retelling, path = example(repo, tmp_path)
    other = start(
        repo, "demo-other", retelling.base, retelling.target, tmp_path / "other", 80, 6
    )
    entries = json.loads(runner.invoke(cli, ["list", "--json"]).output)
    assert [e["name"] for e in entries] == ["demo", "demo-other"]
    assert entries[0]["worktrees"] == [str(path)]
    assert entries[1]["context"] == 6 and entries[1]["budget"] == 80
    before = git(repo, "show-ref")
    result = runner.invoke(cli, ["delete", "demo"])
    assert result.exit_code == 1 and "--remove-worktree" in result.output
    assert git(repo, "show-ref") == before and path.exists()
    result = runner.invoke(cli, ["delete", "demo", "--remove-worktree"])
    assert result.exit_code == 0, result.output
    assert not path.exists()
    assert resolve(repo, "main") == retelling.target
    assert resolve(repo, "refs/heads/retell/demo-other") == other.tip
    assert "retell.demo." not in git(repo, "config", "--local", "--list")
    assert [
        e["name"] for e in json.loads(runner.invoke(cli, ["list", "--json"]).output)
    ] == ["demo-other"]
    assert runner.invoke(cli, ["delete", "demo"]).exit_code == 1


def test_delete_keeps_detached_worktree_and_handles_incomplete_refs(repo, tmp_path):

    retelling, path = example(repo, tmp_path)
    git(path, "switch", "--detach")
    git(repo, "update-ref", "-d", "refs/retell/demo/target")
    runner = CliRunner()
    entries = json.loads(runner.invoke(cli, ["list", "--json"]).output)
    assert "error" in entries[0]
    result = runner.invoke(cli, ["delete", "demo"])
    assert result.exit_code == 0, result.output
    assert (path / "code.txt").read_text() == "before\n"
    assert resolve(repo, "main") == retelling.target
    assert json.loads(runner.invoke(cli, ["list", "--json"]).output) == []


def test_context_flags_and_legacy_defaults(repo, tmp_path, monkeypatch):

    original = [f"line {i}\n" for i in range(40)]
    (repo / "code.txt").write_text("".join(original))
    base = commit(repo, "Before with context")
    original[20] = "replacement\n"
    target_text = "".join(original)
    (repo / "code.txt").write_text(target_text)
    target = commit(repo, "After")
    runner = CliRunner()
    path = tmp_path / "author"
    result = runner.invoke(
        cli,
        [
            "start",
            "demo",
            "--base",
            base,
            "--target",
            target,
            "--worktree",
            str(path),
            "--budget",
            "8",
            "--context",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output
    (path / "code.txt").write_text(target_text)
    commit(path, "Explain")
    small = runner.invoke(cli, ["validate", "demo", "--json"])
    large = runner.invoke(cli, ["validate", "demo", "--context", "6", "--json"])
    assert small.exit_code == 0 and large.exit_code == 1
    a, b = json.loads(small.output), json.loads(large.output)
    assert a["context"] == 0 and b["context"] == 6
    assert a["real_presentation_lines"] < b["real_presentation_lines"]
    assert a["synthetic_churn"] == b["synthetic_churn"]
    assert " line 14\n" not in runner.invoke(cli, ["show", "demo"]).output
    assert " line 14\n" in runner.invoke(cli, ["show", "demo", "--context", "6"]).output
    assert Retelling.load(repo, "demo").context == 0
    calls = []
    monkeypatch.setattr(
        "git_retell.cli.view_retelling",
        lambda retelling, context: calls.append((retelling.context, context)),
    )
    assert runner.invoke(cli, ["view", "demo", "--context", "6"]).exit_code == 0
    assert calls == [(0, 6)]
    assert resolve(repo, "main") == target
    for command in ("show", "view", "validate"):
        assert runner.invoke(cli, [command, "demo", "--context", "-1"]).exit_code == 2
    git(repo, "config", "--unset", "retell.demo.context")
    assert Retelling.load(repo, "demo").context == 3
    assert (
        json.loads(runner.invoke(cli, ["validate", "demo", "--json"]).output)["context"]
        == 3
    )


def test_help_has_examples_for_every_command():
    runner = CliRunner()
    for name in cli.commands:
        result = runner.invoke(cli, [name, "--help"])
        assert result.exit_code == 0
        assert "Examples:" in result.output
        assert f"git-retell {name}" in result.output

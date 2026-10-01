import json
import shutil

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
    (path / "notes").write_text("unsaved\n")
    result = runner.invoke(cli, ["delete", "demo"])
    assert result.exit_code == 1 and "untracked" in result.output
    assert git(repo, "show-ref") == before and path.exists()
    (path / "notes").unlink()
    result = runner.invoke(cli, ["delete", "demo"])
    assert result.exit_code == 0, result.output
    assert not path.exists()
    assert resolve(repo, "main") == retelling.target
    assert resolve(repo, "refs/heads/retell/demo-other") == other.tip
    assert git(repo, "for-each-ref", "refs/retell/demo/") == ""
    assert [
        e["name"] for e in json.loads(runner.invoke(cli, ["list", "--json"]).output)
    ] == ["demo-other"]
    assert runner.invoke(cli, ["delete", "demo"]).exit_code == 1


def test_finish_and_resume(repo, tmp_path):

    retelling, path = example(repo, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["finish", "demo"])
    assert result.exit_code == 1 and "INVALID" in result.output
    assert path.exists()
    (path / "code.txt").write_text("after\n")
    (path / "notes").write_text("unsaved\n")
    git(path, "add", "code.txt")
    git(path, "commit", "-m", "Explain the change")
    result = runner.invoke(cli, ["finish", "demo"])
    assert result.exit_code == 1 and "untracked" in result.output
    assert path.exists()
    (path / "notes").unlink()
    result = runner.invoke(cli, ["finish", "demo"])
    assert result.exit_code == 0, result.output
    assert "VALID" in result.output and f"Removed worktree: {path}" in result.output
    assert not path.exists()
    tip = refresh(retelling).tip
    assert (
        json.loads(runner.invoke(cli, ["list", "--json"]).output)[0]["worktrees"] == []
    )

    again = tmp_path / "again"
    result = runner.invoke(cli, ["resume", "demo", "--worktree", str(again)])
    assert result.exit_code == 0, result.output
    assert "Steps: 1" in result.output
    assert resolve(again, "HEAD") == tip
    assert git(again, "branch", "--show-current").strip() == "retell/demo"
    result = runner.invoke(cli, ["resume", "demo", "--worktree", str(tmp_path / "x")])
    assert result.exit_code == 1 and "already checked out" in result.output
    assert (
        runner.invoke(
            cli, ["resume", "nope", "--worktree", str(tmp_path / "y")]
        ).exit_code
        == 1
    )
    assert runner.invoke(cli, ["finish", "demo"]).exit_code == 0
    assert not again.exists()


def test_finish_and_resume_clear_only_their_stale_worktrees(repo, tmp_path):

    retelling, path = example(repo, tmp_path)
    (path / "code.txt").write_text("after\n")
    git(path, "commit", "-am", "Explain the change")
    unrelated = tmp_path / "unrelated"
    git(repo, "worktree", "add", "--detach", str(unrelated))
    shutil.rmtree(unrelated)
    (path / ".git").unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["finish", "demo"])
    assert result.exit_code == 0, result.output
    assert f"Left non-Git leftovers on disk: {path}" in result.output
    listed = git(repo, "worktree", "list", "--porcelain")
    assert str(path) not in listed and str(unrelated) in listed

    again = tmp_path / "again"
    git(repo, "worktree", "add", str(again), "retell/demo")
    shutil.rmtree(again)
    result = runner.invoke(cli, ["resume", "demo", "--worktree", str(again)])
    assert result.exit_code == 0, result.output
    assert resolve(again, "HEAD") == refresh(retelling).tip
    assert str(unrelated) in git(repo, "worktree", "list", "--porcelain")


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
        lambda retelling, context, pathspecs: calls.append(
            (retelling.context, context)
        ),
    )
    assert runner.invoke(cli, ["view", "demo", "--context", "6"]).exit_code == 0
    assert calls == [(0, 6)]
    assert resolve(repo, "main") == target
    for command in ("show", "view", "validate"):
        assert runner.invoke(cli, [command, "demo", "--context", "-1"]).exit_code == 2
    blob = git(
        repo, "hash-object", "-w", "--stdin", input_text='{"budget": 8}\n'
    ).strip()
    git(repo, "update-ref", "refs/retell/demo/settings", blob)
    assert Retelling.load(repo, "demo").context == 3
    assert (
        json.loads(runner.invoke(cli, ["validate", "demo", "--json"]).output)["context"]
        == 3
    )


def test_configure_updates_settings_blob(repo, tmp_path):
    example(repo, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["configure", "demo"])
    assert result.exit_code == 0 and "budget 60 · context 3" in result.output
    result = runner.invoke(cli, ["configure", "demo", "--context", "6"])
    assert result.exit_code == 0 and "budget 60 · context 6" in result.output
    stored = git(repo, "cat-file", "blob", "refs/retell/demo/settings")
    assert json.loads(stored) == {"budget": 60, "context": 6, "partial": False}
    assert "retell." not in git(repo, "config", "--local", "--list")
    assert runner.invoke(cli, ["configure", "demo", "--budget", "0"]).exit_code == 2
    assert runner.invoke(cli, ["configure", "missing"]).exit_code == 1
    for text in (
        "[]",
        "not json",
        '{"budget": "60"}',
        '{"context": -1}',
        '{"partial": 1}',
    ):
        blob = git(repo, "hash-object", "-w", "--stdin", input_text=text).strip()
        git(repo, "update-ref", "refs/retell/demo/settings", blob)
        result = runner.invoke(cli, ["validate", "demo"])
        assert result.exit_code == 1 and "refs/retell/demo/settings" in result.output


def test_help_has_examples_for_every_command():
    runner = CliRunner()
    for name in cli.commands:
        result = runner.invoke(cli, [name, "--help"])
        assert result.exit_code == 0
        assert "Examples:" in result.output
        assert f"git-retell {name}" in result.output


def test_start_partial_from_scratch_and_configure(repo, tmp_path):
    (repo / "code.txt").write_text("after\n")
    (repo / "uv.lock").write_text("generated\n")
    commit(repo, "Real change")
    runner = CliRunner()
    path = tmp_path / "fresh"
    result = runner.invoke(
        cli,
        ["start", "fresh", "--target", "HEAD", "--worktree", str(path), "--partial"],
    )
    assert result.exit_code == 0, result.output
    assert "from scratch" in result.output and "partial" in result.output
    (path / "code.txt").write_text("after\n")
    commit(path, "Write the code")
    result = runner.invoke(cli, ["validate", "fresh"])
    assert result.exit_code == 0, result.output
    assert "(partial) (from scratch): VALID" in result.output
    assert "Not retold (1 files" in result.output and "uv.lock" in result.output
    result = runner.invoke(cli, ["configure", "fresh", "--no-partial"])
    assert "complete" in result.output
    result = runner.invoke(cli, ["validate", "fresh", "--json"])
    assert result.exit_code == 1 and not json.loads(result.output)["partial"]


def test_show_filters_files_and_skips_steps(repo, tmp_path):
    _, path = example(repo, tmp_path)
    (path / "notes.md").write_text("draft\n")
    commit(path, "Only notes")
    (path / "notes.md").unlink()
    (path / "code.txt").write_text("after\n")
    commit(path, "Code and cleanup")
    runner = CliRunner()
    result = runner.invoke(cli, ["show", "demo", "--all", "--exclude", "*.md"])
    assert result.exit_code == 0, result.output
    assert "Only notes" not in result.output and "notes.md" not in result.output
    assert "2/2" in result.output and "filtered" in result.output
    result = runner.invoke(cli, ["show", "demo", "--step", "1", "--path", "code.txt"])
    assert "No changes to the selected files" in result.output
    # Filters change only what is shown; validation still covers every file.
    assert runner.invoke(cli, ["validate", "demo"]).exit_code == 0

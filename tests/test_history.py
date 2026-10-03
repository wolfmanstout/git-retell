import json
import sys

from click.testing import CliRunner

from git_retell.cli import cli
from git_retell.git import empty_tree, git, resolve
from git_retell.history import History
from git_retell.web import payload

from .helpers import commit


def feature_branch(repo):
    """main gains a commit after feature forks; feature adds then rewrites a line."""
    fork = resolve(repo, "HEAD")
    git(repo, "switch", "-c", "feature")
    (repo / "code.txt").write_text("before\ndraft\n")
    first = commit(repo, "Draft a line")
    (repo / "code.txt").write_text("before\nfinal\n")
    second = commit(repo, "Rewrite it")
    git(repo, "switch", "main")
    (repo / "other.txt").write_text("main moved on\n")
    commit(repo, "Unrelated main work")
    git(repo, "switch", "feature")
    return fork, first, second


def test_history_starts_where_the_branch_forked(repo):
    fork, first, second = feature_branch(repo)
    history = History.load(repo, "main", "feature", "main..feature")
    assert history.base == fork and history.commits() == [first, second]
    result = CliRunner().invoke(cli, ["show", "--from", "main", "--all"])
    assert result.exit_code == 0, result.output
    headings = [
        line for line in result.output.splitlines() if line.startswith("History")
    ]
    assert len(headings) == 2
    assert headings[0].startswith(
        f"History · main..HEAD · 1/2 · {first[:8]} · Retell Test"
    )
    assert "other.txt" not in result.output and "SYNTHETIC" not in result.output


def test_history_follows_first_parents_through_merges(repo):
    fork, first, second = feature_branch(repo)
    git(repo, "merge", "--no-ff", "-m", "Merge main", "main")
    history = History.load(repo, fork, "HEAD", "range")
    merge = resolve(repo, "HEAD")
    assert history.commits() == [first, second, merge]
    result = CliRunner().invoke(cli, ["show", "--from", "main", "--all"])
    # Every commit of main is excluded, so the merge shows only its own slide.
    headings = [
        line for line in result.output.splitlines() if line.startswith("History")
    ]
    assert result.exit_code == 0 and len(headings) == 3


def test_history_from_scratch_starts_at_the_empty_tree(repo):
    history = History.load(repo, None, "HEAD", "HEAD")
    assert history.base == empty_tree(repo) and len(history.commits()) == 1
    result = CliRunner().invoke(cli, ["show", "--from-scratch"])
    assert result.exit_code == 0 and "+before" in result.output


def test_history_page_marks_rework_without_validation(repo):
    feature_branch(repo)
    data = payload(History.load(repo, "main", "feature", "main..feature"))
    assert (
        data["history"] and data["budget"] is None and data["name"] == "main..feature"
    )
    assert [s["author"] for s in data["slides"]] == ["Retell Test"] * 2
    # The drafted line is removed by the next commit; the rewrite survives.
    draft = data["text"].index("draft")
    assert data["ends"][draft] == 1 and draft in data["rewritten"]
    assert data["ends"][data["text"].index("final")] == -1
    # Two changed lines in total against one net added line.
    assert data["expansion"] == 3


def test_web_and_test_accept_ranges(repo, tmp_path):
    feature_branch(repo)
    runner = CliRunner()
    output = tmp_path / "page.html"
    result = runner.invoke(
        cli, ["web", "--from", "main", "--no-open", "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert "main..HEAD · git-retell" in output.read_text()
    command = [
        sys.executable,
        "-c",
        "import pathlib; assert 'final' in pathlib.Path('code.txt').read_text()",
    ]
    result = runner.invoke(cli, ["test", "--from", "main", "--json", "--", *command])
    assert result.exit_code == 1
    assert [r["passed"] for r in json.loads(result.output)] == [False, True]


def test_uncommitted_work_becomes_a_final_slide(repo):
    feature_branch(repo)
    (repo / "code.txt").write_text("before\nfinal\nwip\n")
    result = CliRunner().invoke(
        cli, ["show", "--from", "main", "--to-uncommitted", "--all"]
    )
    assert result.exit_code == 0, result.output
    assert "History · main..uncommitted · 3/3" in result.output
    assert "SYNTHETIC snapshot of uncommitted changes" in result.output
    assert "+wip" in result.output


def test_name_and_range_are_exclusive(repo):
    runner = CliRunner()
    result = runner.invoke(cli, ["show", "demo", "--from", "main"])
    assert result.exit_code == 2 and "not both" in result.output
    result = runner.invoke(cli, ["view"])
    assert result.exit_code == 2 and "--from REV" in result.output
    result = runner.invoke(cli, ["show", "--to", "HEAD"])
    assert result.exit_code == 2
    result = runner.invoke(cli, ["test", "--from", "HEAD~0"])
    assert result.exit_code == 2 and "Missing COMMAND" in result.output

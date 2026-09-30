import click
import pytest

from git_retell.git import diff, git, resolve
from git_retell.retelling import delete, inspect, start, worktrees

from .helpers import commit, example, refresh


def test_endpoints_and_temporary_implementation(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
    assert not inspect(retelling)["valid"]
    (path / "code.txt").write_text("naive\n")
    commit(path, "Introduce a naive solution")
    (path / "code.txt").write_text("after\n")
    commit(path, "Generalize to the final implementation")
    report = inspect(refresh(retelling))
    assert report["valid"] and report["step_count"] == 2
    assert report["expansion_factor"] == 2
    assert report["tip_tree"] == report["target_tree"]
    assert git(path, "rev-parse", "HEAD~2").strip() == retelling.base


def test_exact_tree_includes_extra_files_and_modes(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
    (path / "code.txt").write_text("after\n")
    (path / "extra").write_text("not submitted\n")
    commit(path, "Extra file")
    assert not inspect(refresh(retelling))["valid"]
    (path / "extra").unlink()
    (path / "code.txt").chmod(0o755)
    commit(path, "Wrong mode")
    assert not inspect(refresh(retelling))["valid"]


def test_budget_uses_actual_diff_and_boundary(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
    (path / "code.txt").write_text("after\n")
    tip = commit(path, "One step")
    patch = diff(repo, retelling.base, tip)
    size = len(patch.splitlines())
    report = inspect(refresh(retelling), size)
    assert report["valid"]
    assert report["steps"][0]["presentation_lines"] == size
    assert not inspect(refresh(retelling), size - 1)["valid"]


def test_binary_patches_are_budgeted(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
    (path / "blob").write_bytes(b"\0\xff\x01" * 30)
    tip = commit(path, "Binary")
    patch = diff(repo, retelling.base, tip)
    assert "GIT binary patch" in patch
    report = inspect(refresh(retelling))
    assert report["steps"][0]["binary_files"] == 1
    assert report["expansion_factor"] is None
    assert not inspect(refresh(retelling), 1)["valid"]


def test_merge_and_wrong_base_are_rejected(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
    git(path, "merge", "--no-ff", retelling.target, "-m", "Merge is not a slide")
    assert any("parent" in issue for issue in inspect(refresh(retelling))["issues"])
    git(path, "checkout", "--orphan", "unrelated")
    tip = commit(path, "Identical target tree without the base")
    git(repo, "update-ref", "refs/heads/retell/demo", tip)
    report = inspect(refresh(retelling))
    assert report["tip_tree"] == report["target_tree"]
    assert not report["valid"]


def test_ancestor_tip_and_zero_diff(repo, tmp_path):
    base = resolve(repo, "HEAD")
    retelling = start(repo, "same", base, base, tmp_path / "same", 60)
    report = inspect(retelling)
    assert report["valid"] and report["expansion_factor"] is None
    commit(repo, "Empty real commit")
    retelling = start(repo, "ancestor", "HEAD", "HEAD", tmp_path / "ancestor", 60)
    git(repo, "update-ref", "refs/heads/retell/ancestor", base)
    assert not inspect(refresh(retelling))["valid"]


def test_pinned_target_survives_branch_motion(repo, tmp_path):
    retelling, _ = example(repo, tmp_path)
    (repo / "code.txt").write_text("later\n")
    commit(repo, "Move main")
    assert refresh(retelling).target == retelling.target


@pytest.mark.parametrize("state", ["tracked", "untracked", "locked", "current"])
def test_delete_protects_worktrees(repo, tmp_path, monkeypatch, state):

    retelling, path = example(repo, tmp_path)
    if state == "tracked":
        (path / "code.txt").write_text("unsaved\n")
    elif state == "untracked":
        (path / "notes").write_text("keep me\n")
    elif state == "locked":
        git(repo, "worktree", "lock", str(path))
    elif state == "current":
        monkeypatch.chdir(path)
    with pytest.raises(click.ClickException):
        delete(repo, "demo")
    assert path.exists()
    assert refresh(retelling) == retelling


def test_delete_removes_ignored_files(repo, tmp_path):

    _, path = example(repo, tmp_path)
    git(repo, "config", "core.excludesFile", str(tmp_path / "ignore"))
    (tmp_path / "ignore").write_text("build/\n")
    (path / "build").mkdir()
    (path / "build" / "out").write_text("regenerable\n")
    delete(repo, "demo")
    assert not path.exists()


def test_worktree_paths_with_newlines(repo, tmp_path):

    base = resolve(repo, "HEAD")
    path = tmp_path / "author space\nand newline"
    start(repo, "odd", base, base, path, 60)
    assert worktrees(repo, "odd")[0]["worktree"] == str(path)
    delete(repo, "odd")
    assert not path.exists()

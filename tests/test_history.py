from git_retell.git import diff, git, resolve
from git_retell.history import inspect, start

from .helpers import commit, example, refresh


def test_endpoints_and_temporary_implementation(repo, tmp_path):
    history, path = example(repo, tmp_path)
    assert not inspect(history)["valid"]
    (path / "code.txt").write_text("naive\n")
    commit(path, "Introduce a naive solution")
    (path / "code.txt").write_text("after\n")
    commit(path, "Generalize to the final implementation")
    report = inspect(refresh(history))
    assert report["valid"] and report["step_count"] == 2
    assert report["expansion_factor"] == 2
    assert report["tip_tree"] == report["target_tree"]
    assert git(path, "rev-parse", "HEAD~2").strip() == history.base


def test_exact_tree_includes_extra_files_and_modes(repo, tmp_path):
    history, path = example(repo, tmp_path)
    (path / "code.txt").write_text("after\n")
    (path / "extra").write_text("not submitted\n")
    commit(path, "Extra file")
    assert not inspect(refresh(history))["valid"]
    (path / "extra").unlink()
    (path / "code.txt").chmod(0o755)
    commit(path, "Wrong mode")
    assert not inspect(refresh(history))["valid"]


def test_budget_uses_actual_diff_and_boundary(repo, tmp_path):
    history, path = example(repo, tmp_path)
    (path / "code.txt").write_text("after\n")
    tip = commit(path, "One step")
    patch = diff(repo, history.base, tip)
    size = len(patch.splitlines())
    report = inspect(refresh(history), size)
    assert report["valid"]
    assert report["steps"][0]["presentation_lines"] == size
    assert not inspect(refresh(history), size - 1)["valid"]


def test_binary_patches_are_budgeted(repo, tmp_path):
    history, path = example(repo, tmp_path)
    (path / "blob").write_bytes(b"\0\xff\x01" * 30)
    tip = commit(path, "Binary")
    patch = diff(repo, history.base, tip)
    assert "GIT binary patch" in patch
    report = inspect(refresh(history))
    assert report["steps"][0]["binary_files"] == 1
    assert report["expansion_factor"] is None
    assert not inspect(refresh(history), 1)["valid"]


def test_merge_and_wrong_base_are_rejected(repo, tmp_path):
    history, path = example(repo, tmp_path)
    git(path, "merge", "--no-ff", history.target, "-m", "Merge is not a slide")
    assert any("parent" in issue for issue in inspect(refresh(history))["issues"])
    git(path, "checkout", "--orphan", "unrelated")
    tip = commit(path, "Identical target tree without the base")
    git(repo, "update-ref", "refs/heads/retell/demo", tip)
    report = inspect(refresh(history))
    assert report["tip_tree"] == report["target_tree"]
    assert not report["valid"]


def test_ancestor_tip_and_zero_diff(repo, tmp_path):
    base = resolve(repo, "HEAD")
    history = start(repo, "same", base, base, tmp_path / "same", 60)
    report = inspect(history)
    assert report["valid"] and report["expansion_factor"] is None
    commit(repo, "Empty real commit")
    history = start(repo, "ancestor", "HEAD", "HEAD", tmp_path / "ancestor", 60)
    git(repo, "update-ref", "refs/heads/retell/ancestor", base)
    assert not inspect(refresh(history))["valid"]


def test_pinned_target_survives_branch_motion(repo, tmp_path):
    history, _ = example(repo, tmp_path)
    (repo / "code.txt").write_text("later\n")
    commit(repo, "Move main")
    assert refresh(history).target == history.target

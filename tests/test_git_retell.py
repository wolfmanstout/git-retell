import json
import os
from pathlib import Path
import sys

from click.testing import CliRunner
import pytest

from git_retell import checks, viewer
from git_retell.cli import cli
from git_retell.git import churn, diff, git, line_count, resolve
from git_retell.history import History, inspect, start


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Retell Test")
    git(path, "config", "user.email", "retell@example.invalid")
    (path / "code.txt").write_text("before\n")
    commit(path, "Before")
    monkeypatch.chdir(path)
    return path


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


def test_help_and_version():
    runner = CliRunner()
    assert runner.invoke(cli, ["--version"]).exit_code == 0
    help_text = runner.invoke(cli, ["--help"]).output
    assert "SYNTHETIC" in help_text and "EXACTLY" in help_text


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


def test_scattered_edits_cost_more_context(repo):
    original = [f"line {i}\n" for i in range(80)]
    (repo / "code.txt").write_text("".join(original))
    base = commit(repo, "Many lines")
    contiguous = original.copy()
    contiguous[20:22] = ["changed A\n", "changed B\n"]
    (repo / "code.txt").write_text("".join(contiguous))
    first = commit(repo, "Contiguous")
    scattered = original.copy()
    scattered[20], scattered[60] = "changed A\n", "changed B\n"
    (repo / "code.txt").write_text("".join(scattered))
    second = commit(repo, "Scattered")
    assert churn(repo, base, first) == churn(repo, base, second)
    assert line_count(diff(repo, base, second)) > line_count(diff(repo, base, first))


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


def test_churn_handles_tabs_and_newlines_in_paths(repo):
    base = resolve(repo, "HEAD")
    (repo / "odd\tname\n.txt").write_text("one\ntwo\n")
    tip = commit(repo, "Odd filename")
    assert churn(repo, base, tip) == {"added": 2, "deleted": 0, "binary_files": 0}


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


def test_start_rejects_collisions_without_changing_history(repo, tmp_path):
    history, path = example(repo, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["start", "demo", "--base", "HEAD", "--target", "HEAD",
                                 "--worktree", str(path)])
    assert result.exit_code != 0 and "already exists" in result.output
    assert refresh(history) == history
    result = runner.invoke(cli, ["start", "../bad", "--base", "HEAD", "--target", "HEAD",
                                 "--worktree", str(tmp_path / "bad")])
    assert result.exit_code != 0


def test_cli_validate_show_and_nonterminal_view(repo, tmp_path):
    history, path = example(repo, tmp_path)
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


def test_checks_report_failures_and_clean_worktrees(repo, tmp_path):
    history, path = example(repo, tmp_path)
    (path / "code.txt").write_text("naive\n")
    commit(path, "Intermediate")
    (path / "code.txt").write_text("after\n")
    commit(path, "Final")
    before = git(repo, "worktree", "list", "--porcelain")
    command = (sys.executable, "-c", "from pathlib import Path; "
               "assert Path('code.txt').read_text() == 'after\\n'")
    result = CliRunner().invoke(cli, ["check", "demo", "--timeout", "2", "--", *command])
    assert result.exit_code == 1
    assert [r["passed"] for r in json.loads(result.output)] == [False, True]
    assert git(repo, "worktree", "list", "--porcelain") == before
    assert inspect(refresh(history))["valid"]


def test_check_timeout_and_missing_command(repo):
    result = checks.run_check(repo, (sys.executable, "-c", "import time; time.sleep(10)"), 0.02)
    assert result["timed_out"] and not result["passed"]
    assert not checks.run_check(repo, ("/nonexistent-retell-command",), 1)["passed"]


def test_terminal_controls_and_width():
    assert viewer.safe_text("\x1b[2J\rfoo") == "\\x1b[2J\\x0dfoo"
    assert viewer.dimensions("界e\u0301\nhi") == (3, 2)
    assert line_count("a\rb\n") == 1
    assert viewer.wrap_lines("abcdefgh\n界e\u0301", 3) == "abc\ndef\ngh\n界e\u0301"


def test_viewer_navigation_and_resize(repo, tmp_path, monkeypatch):
    history, path = example(repo, tmp_path)
    (path / "code.txt").write_text("naive\n")
    commit(path, "First explanation")
    (path / "code.txt").write_text("after\n")
    commit(path, "Second explanation")
    monkeypatch.setattr(viewer.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(viewer.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(viewer.shutil, "get_terminal_size", lambda: os.terminal_size((150, 70)))
    outputs = []
    monkeypatch.setattr(viewer.click, "echo", outputs.append)
    monkeypatch.setattr(viewer.click, "clear", lambda: None)
    keys = iter(["n", "p", "q"])
    monkeypatch.setattr(viewer.click, "getchar", lambda: next(keys))
    viewer.view(refresh(history))
    assert ["First explanation" in output for output in outputs] == [True, False, True]
    outputs.clear()
    monkeypatch.setattr(viewer.shutil, "get_terminal_size", lambda: os.terminal_size((30, 8)))
    monkeypatch.setattr(viewer.click, "getchar", lambda: "q")
    viewer.view(refresh(history))
    assert "SYNTHETIC" in outputs[0]
    assert viewer.dimensions(outputs[0])[1] < 8
    assert "needs at least" not in outputs[0]


@pytest.mark.parametrize('columns,rows', [(179, 74), (80, 24), (30, 8), (12, 4)])
def test_paging_keeps_every_wrapped_line_accessible(columns, rows):
    content = '\n'.join(f'{i}: ' + 'long line 界 ' * 8 for i in range(50))
    expected = viewer.wrap_lines(content, columns - 1).split('\n')
    offset, seen = 0, set()
    while True:
        frame, offset, height, bottom = viewer.page(content, 'VALID 1/2 U3', offset, columns, rows)
        width, frame_rows = viewer.dimensions(frame)
        assert width < columns and frame_rows < rows
        visible = expected[offset:offset + height]
        assert frame.split('\n')[:len(visible)] == visible
        seen.update(range(offset, offset + len(visible)))
        if offset == bottom:
            break
        offset += height
    assert seen == set(range(len(expected)))
    _, offset, _, bottom = viewer.page(content, 'VALID 1/2 U3', 99999, columns, rows)
    assert offset == bottom
    assert viewer.page(content, 'VALID 1/2 U3', -100, columns, rows)[1] == 0


def test_context_changes_view_but_not_validation(repo, tmp_path):
    original = [f'line {i}\n' for i in range(40)]
    (repo / 'code.txt').write_text(''.join(original))
    commit(repo, 'Context')
    changed = original.copy()
    changed[20] = 'replacement\n'
    history, path = example(repo, tmp_path, ''.join(changed))
    (path / 'code.txt').write_text(''.join(changed))
    commit(path, 'Change surrounded by unchanged code')
    history = refresh(history)
    baseline = inspect(history)
    small = viewer.slide(history, history.commits(), 0, context=0)
    expanded = viewer.slide(history, history.commits(), 0, context=9)
    assert ' line 12\n' not in small and ' line 12\n' in expanded
    assert '-line 20\n' in small and '-line 20\n' in expanded
    assert '+replacement\n' in small and '+replacement\n' in expanded
    assert inspect(history) == baseline
    assert History.load(repo, 'demo').budget == history.budget


def test_viewer_context_paging_and_resize(repo, tmp_path, monkeypatch):
    original = ''.join(f'line {i}\n' for i in range(70))
    (repo / 'code.txt').write_text(original)
    commit(repo, 'Context')
    changed = original.replace('line 30\n', 'replacement\n')
    history, path = example(repo, tmp_path, changed)
    (path / 'code.txt').write_text(original.replace('line 30\n', 'naive\n'))
    commit(path, 'First explanation')
    (path / 'code.txt').write_text(changed)
    commit(path, 'Second explanation')
    history = refresh(history)
    monkeypatch.setattr(viewer.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(viewer.sys.stdout, 'isatty', lambda: True)
    size = [os.terminal_size((80, 12))]
    monkeypatch.setattr(viewer.shutil, 'get_terminal_size', lambda: size[0])
    outputs = []
    monkeypatch.setattr(viewer.click, 'echo', outputs.append)
    monkeypatch.setattr(viewer.click, 'clear', lambda: None)
    keys = iter(['+', 'n', '-', '-', '-', '0', 'f', 'b', 'j', 'k', 'G', 'resize', 'g', 'q'])

    def key():
        value = next(keys)
        if value == 'resize':
            size[0] = os.terminal_size((120, 74))
            return 'r'
        return value

    monkeypatch.setattr(viewer.click, 'getchar', key)
    viewer.view(history)
    assert '1/2 U6' in outputs[1] and '2/2 U6' in outputs[2]
    assert '2/2 U0' in outputs[4] and '2/2 U0' in outputs[5]
    assert '2/2 U3' in outputs[6]
    assert outputs[7] != outputs[6] and outputs[8] == outputs[6]
    assert outputs[9] != outputs[8] and outputs[10] == outputs[8]
    assert '+replacement' in outputs[11]  # End reaches the actual changed line.
    assert 'Second explanation' in outputs[12]  # Resize clamps the old bottom offset.
    assert all(viewer.dimensions(frame)[1] < 12 for frame in outputs[:12])


def test_space_pages_before_advancing(repo, tmp_path, monkeypatch):
    history, path = example(repo, tmp_path)
    (path / 'code.txt').write_text('naive\n')
    commit(path, 'First explanation')
    (path / 'code.txt').write_text('after\n')
    commit(path, 'Second explanation')
    monkeypatch.setattr(viewer.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(viewer.sys.stdout, 'isatty', lambda: True)
    monkeypatch.setattr(viewer.shutil, 'get_terminal_size', lambda: os.terminal_size((80, 12)))
    outputs = []
    monkeypatch.setattr(viewer.click, 'echo', outputs.append)
    monkeypatch.setattr(viewer.click, 'clear', lambda: None)
    keys = iter([' ', 'G', ' ', '\x1b[D', '\x1b[6~', '\x1b[5~', 'q'])
    monkeypatch.setattr(viewer.click, 'getchar', lambda: next(keys))
    viewer.view(refresh(history))
    assert '1/2 U3' in outputs[1] and outputs[1] != outputs[0]
    assert '2/2 U3' in outputs[3]
    assert '1/2 U3' in outputs[4]
    assert outputs[5] != outputs[4] and outputs[6] == outputs[4]

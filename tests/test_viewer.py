import os

import pytest

from git_retell import viewer
from git_retell.git import line_count
from git_retell.history import History, inspect

from .helpers import commit, example, refresh


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
    monkeypatch.setattr(
        viewer.shutil, "get_terminal_size", lambda: os.terminal_size((150, 70))
    )
    outputs = []
    monkeypatch.setattr(viewer.click, "echo", outputs.append)
    monkeypatch.setattr(viewer.click, "clear", lambda: None)
    keys = iter(["n", "p", "q"])
    monkeypatch.setattr(viewer.click, "getchar", lambda: next(keys))
    viewer.view(refresh(history))
    assert ["First explanation" in output for output in outputs] == [True, False, True]
    outputs.clear()
    monkeypatch.setattr(
        viewer.shutil, "get_terminal_size", lambda: os.terminal_size((30, 8))
    )
    monkeypatch.setattr(viewer.click, "getchar", lambda: "q")
    viewer.view(refresh(history))
    assert "SYNTHETIC" in outputs[0]
    assert viewer.dimensions(outputs[0])[1] < 8
    assert "needs at least" not in outputs[0]


@pytest.mark.parametrize("columns,rows", [(179, 74), (80, 24), (30, 8), (12, 4)])
def test_paging_keeps_every_wrapped_line_accessible(columns, rows):
    content = "\n".join(f"{i}: " + "long line 界 " * 8 for i in range(50))
    expected = viewer.wrap_lines(content, columns - 1).split("\n")
    offset, seen = 0, set()
    while True:
        frame, offset, height, bottom = viewer.page(
            content, "VALID 1/2 U3", offset, columns, rows
        )
        width, frame_rows = viewer.dimensions(frame)
        assert width < columns and frame_rows < rows
        visible = expected[offset : offset + height]
        assert frame.split("\n")[: len(visible)] == visible
        seen.update(range(offset, offset + len(visible)))
        if offset == bottom:
            break
        offset += height
    assert seen == set(range(len(expected)))
    _, offset, _, bottom = viewer.page(content, "VALID 1/2 U3", 99999, columns, rows)
    assert offset == bottom
    assert viewer.page(content, "VALID 1/2 U3", -100, columns, rows)[1] == 0


def test_context_changes_view_but_not_validation(repo, tmp_path):
    original = [f"line {i}\n" for i in range(40)]
    (repo / "code.txt").write_text("".join(original))
    commit(repo, "Context")
    changed = original.copy()
    changed[20] = "replacement\n"
    history, path = example(repo, tmp_path, "".join(changed))
    (path / "code.txt").write_text("".join(changed))
    commit(path, "Change surrounded by unchanged code")
    history = refresh(history)
    baseline = inspect(history)
    small = viewer.slide(history, history.commits(), 0, context=0)
    expanded = viewer.slide(history, history.commits(), 0, context=9)
    assert " line 12\n" not in small and " line 12\n" in expanded
    assert "-line 20\n" in small and "-line 20\n" in expanded
    assert "+replacement\n" in small and "+replacement\n" in expanded
    assert inspect(history) == baseline
    assert History.load(repo, "demo").budget == history.budget


def test_viewer_context_paging_and_resize(repo, tmp_path, monkeypatch):
    original = "".join(f"line {i}\n" for i in range(70))
    (repo / "code.txt").write_text(original)
    commit(repo, "Context")
    changed = original.replace("line 30\n", "replacement\n")
    history, path = example(repo, tmp_path, changed)
    (path / "code.txt").write_text(original.replace("line 30\n", "naive\n"))
    commit(path, "First explanation")
    (path / "code.txt").write_text(changed)
    commit(path, "Second explanation")
    history = refresh(history)
    monkeypatch.setattr(viewer.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(viewer.sys.stdout, "isatty", lambda: True)
    size = [os.terminal_size((80, 12))]
    monkeypatch.setattr(viewer.shutil, "get_terminal_size", lambda: size[0])
    outputs = []
    monkeypatch.setattr(viewer.click, "echo", outputs.append)
    monkeypatch.setattr(viewer.click, "clear", lambda: None)
    keys = iter(
        ["+", "n", "-", "-", "-", "0", "f", "b", "j", "k", "G", "resize", "g", "q"]
    )

    def key():
        value = next(keys)
        if value == "resize":
            size[0] = os.terminal_size((120, 74))
            return "r"
        return value

    monkeypatch.setattr(viewer.click, "getchar", key)
    viewer.view(history)
    assert "1/2 U6" in outputs[1] and "2/2 U6" in outputs[2]
    assert "2/2 U0" in outputs[4] and "2/2 U0" in outputs[5]
    assert "2/2 U3" in outputs[6]
    assert outputs[7] != outputs[6] and outputs[8] == outputs[6]
    assert outputs[9] != outputs[8] and outputs[10] == outputs[8]
    assert "+replacement" in outputs[11]  # End reaches the actual changed line.
    assert "Second explanation" in outputs[12]  # Resize clamps the old bottom offset.
    assert all(viewer.dimensions(frame)[1] < 12 for frame in outputs[:12])


def test_space_pages_before_advancing(repo, tmp_path, monkeypatch):
    history, path = example(repo, tmp_path)
    (path / "code.txt").write_text("naive\n")
    commit(path, "First explanation")
    (path / "code.txt").write_text("after\n")
    commit(path, "Second explanation")
    monkeypatch.setattr(viewer.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(viewer.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        viewer.shutil, "get_terminal_size", lambda: os.terminal_size((80, 12))
    )
    outputs = []
    monkeypatch.setattr(viewer.click, "echo", outputs.append)
    monkeypatch.setattr(viewer.click, "clear", lambda: None)
    keys = iter([" ", "G", " ", "\x1b[D", "\x1b[6~", "\x1b[5~", "q"])
    monkeypatch.setattr(viewer.click, "getchar", lambda: next(keys))
    viewer.view(refresh(history))
    assert "1/2 U3" in outputs[1] and outputs[1] != outputs[0]
    assert "2/2 U3" in outputs[3]
    assert "1/2 U3" in outputs[4]
    assert outputs[5] != outputs[4] and outputs[6] == outputs[4]

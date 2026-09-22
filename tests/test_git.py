from git_retell.git import churn, diff, line_count, resolve

from .helpers import commit


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


def test_churn_handles_tabs_and_newlines_in_paths(repo):
    base = resolve(repo, "HEAD")
    (repo / "odd\tname\n.txt").write_text("one\ntwo\n")
    tip = commit(repo, "Odd filename")
    assert churn(repo, base, tip) == {"added": 2, "deleted": 0, "binary_files": 0}

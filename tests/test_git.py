from git_retell.git import churn, diff, diffs, line_count, log, resolve

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


def test_batched_diffs_match_single_diffs(repo):
    base = resolve(repo, "HEAD")
    (repo / "code.txt").write_text("after\n")
    (repo / "odd\nname.py").write_text("one\n")
    first = commit(repo, "Edit and add")
    same = commit(repo, "Empty")
    pairs = [(base, first), (first, same), (base, first), (same, base)]
    for numstat, context, pathspecs in (
        (True, 3, None),
        (False, 0, None),
        (False, 3, ["*.py"]),
        (False, 3, ["nothing-matches"]),
    ):
        options = {"numstat": numstat, "context": context, "pathspecs": pathspecs}
        expected = [diff(repo, a, b, **options) for a, b in pairs]
        assert diffs(repo, pairs, **options) == expected
    assert diffs(repo, []) == []


def test_log_reads_first_parent_details(repo):
    base = resolve(repo, "HEAD")
    first = commit(repo, "First\n\nBody line.")
    second = commit(repo, "Second")
    history = log(repo, f"{base}..{second}")
    assert list(history) == [first, second]
    assert history[first].parents == [base]
    assert history[first].message == "First\n\nBody line."
    assert history[second].author == "Retell Test"

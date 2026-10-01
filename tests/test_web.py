import json
import os

from click.testing import CliRunner

from git_retell import web
from git_retell.cli import cli
from git_retell.git import git

from .helpers import commit, example, refresh


def author(repo, tmp_path):
    """A history that adds, edits, moves within, deletes, and re-modes files."""
    lines = [f"line {i}" for i in range(40)]
    retelling, path = example(repo, tmp_path, target="after\n")
    (path / "code.txt").write_text("\n".join(lines) + "\n")
    (path / "new.py").write_text('def f():\n    return """a\nb"""\n')
    commit(path, "Synthetic: Add a file\n\nIt uses `f`.")
    lines[2] = "changed near top"
    lines[35] = "changed near bottom"
    (path / "code.txt").write_text("\n".join(lines) + "\n")
    (path / "blob.bin").write_bytes(b"\0\1\2")
    os.chmod(path / "new.py", 0o755)
    commit(path, "Edit two places")
    (path / "new.py").unlink()
    (path / "blob.bin").unlink()
    (path / "code.txt").write_text("after\n")
    commit(path, "Finish")
    return refresh(retelling)


def test_line_identities_reconstruct_every_version(repo, tmp_path):
    retelling = author(repo, tmp_path)
    data = web.payload(retelling)
    first, second, third = data["slides"]
    assert first["subject"] == "Synthetic: Add a file"
    assert [f["status"] for f in first["files"]] == ["M", "A"]
    for slide, previous in zip(data["slides"], [retelling.base, *retelling.commits()]):
        commit_id = slide["commit"]
        for f in slide["files"]:
            if f["binary"]:
                assert "before" not in f
                continue
            for key, rev in (("before", previous), ("after", commit_id)):
                ids = data["versions"][f[key]]
                expected = (
                    git(repo, "show", f"{rev}:{f['path']}")
                    if git(repo, "ls-tree", rev, "--", f["path"]).strip()
                    else ""
                )
                assert "\n".join(data["text"][i] for i in ids) == expected.rstrip("\n")
    # Unchanged lines keep their identity from one slide to the next.
    code_after_first = data["versions"][first["files"][0]["after"]]
    code_second = next(f for f in second["files"] if f["path"] == "code.txt")
    before, after = (data["versions"][code_second[k]] for k in ("before", "after"))
    assert before == code_after_first
    assert len(set(before) & set(after)) == 38
    assert after[0] == before[0] and after[2] != before[2]
    binary = next(f for f in second["files"] if f["path"] == "blob.bin")
    assert binary["binary"] and binary["status"] == "A"
    mode = next(f for f in second["files"] if f["path"] == "new.py")
    assert (mode["oldMode"], mode["newMode"]) == ("100644", "100755")
    assert {f["path"]: f["status"] for f in third["files"]}["new.py"] == "D"


def test_highlighting_spans_multiline_tokens():
    colored = web.highlight("x.py", 'x = """a\n<b>"""\n')
    assert colored is not None and len(colored) == 2
    assert colored[1].startswith('<i class="s">&lt;b&gt;')
    assert web.highlight("unknown.zzz-no-lexer", "text\n") is None


def test_page_escapes_repository_text(repo, tmp_path):
    retelling, path = example(repo, tmp_path)
    (path / "code.txt").write_text("</script><script>alert(1)</script>\n")
    commit(path, "</script> in a message")
    document = web.page(web.payload(refresh(retelling)))
    assert document.count("</script>") == 2
    start = document.index('type="application/json">') + len('type="application/json">')
    data = json.loads(document[start : document.index("</script>", start)])
    assert data["slides"][0]["subject"] == "</script> in a message"


def test_web_command_writes_page(repo, tmp_path):
    author(repo, tmp_path)
    output = tmp_path / "out.html"
    result = CliRunner().invoke(cli, ["web", "demo", "--no-open", "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output
    text = output.read_text()
    assert "<title>demo · git-retell</title>" in text and "__DATA__" not in text


def test_trailers_are_dropped_but_prose_is_kept():
    body = (
        "Explain.\n\nCo-Authored-By: A <a@example.invalid>\nSigned-off-by: B\n  folded"
    )
    assert web.without_trailers(body) == "Explain."
    assert web.without_trailers("Co-Authored-By: A") == ""
    assert web.without_trailers("Explain.\n\nNote: still temporary.") == (
        "Explain.\n\nNote: still temporary."
    )
    assert web.without_trailers("Explain.\n\nFixes: #3\nsee above") == (
        "Explain.\n\nFixes: #3\nsee above"
    )


def test_lifetimes_separate_scaffolding_from_lines_that_reach_the_target(
    repo, tmp_path
):
    final = "def parse(s):\n    tokens = lex(s)\n    return build(tokens)\nkeep\n"
    (repo / "code.txt").write_text("legacy_parse(s)\nkeep\n")
    commit(repo, "Base")
    retelling, path = example(repo, tmp_path, target=final)
    (path / "code.txt").write_text(
        "def parse(s):\n    return None  # stub\nlegacy_parse(s)\nkeep\nscratch\n"
    )
    commit(path, "Add a stub")
    (path / "code.txt").write_text(final)
    commit(path, "Replace the stub and the legacy parser")
    data = web.payload(refresh(retelling))
    text = data["text"]

    def ident(line):
        return next(i for i, t in enumerate(text) if t == line)

    stub, legacy = ident("    return None  # stub"), ident("legacy_parse(s)")
    header, scratch = ident("def parse(s):"), ident("scratch")
    assert (data["origin"][header], data["ends"][header]) == (0, -1)
    assert (data["origin"][ident("keep")], data["ends"][ident("keep")]) == (-1, -1)
    assert (data["origin"][stub], data["ends"][stub]) == (0, 1)
    assert (data["origin"][legacy], data["ends"][legacy]) == (-1, 1)
    assert (data["origin"][scratch], data["ends"][scratch]) == (0, 1)
    # The stub and legacy line were replaced; the trailing scratch line was not.
    assert stub in data["rewritten"] and scratch not in data["rewritten"]
    ids = data["versions"][data["targetVersions"]["code.txt"]]
    assert [text[i] for i in ids] == final.splitlines()
    assert all(data["ends"][i] == -1 for i in ids)

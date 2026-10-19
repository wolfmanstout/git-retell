"""Small Git boundary; all review diffs use the same rendering settings."""

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

import click


def git(
    repo: Path,
    *args: str,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        input=input_text.encode() if input_text is not None else None,
        capture_output=True,
        check=False,
        env={**os.environ, **env} if env else None,
    )
    if result.returncode:
        raise click.ClickException(result.stderr.decode(errors="replace").strip())
    return result.stdout.decode("utf-8", errors="replace")


def root() -> Path:
    return Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())


def resolve(repo: Path, revision: str, kind: str = "commit") -> str:
    return git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{{kind}}}"
    ).strip()


# Plumbing ignores most diff configuration; these pin the rest.
CONFIG = ["-c", "core.quotePath=true", "-c", "diff.suppressBlankEmpty=false"]


def review_options(numstat: bool, context: int) -> list[str]:
    return [
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--no-relative",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--line-prefix=",
        f"--unified={context}",
        "--inter-hunk-context=0",
        "--diff-algorithm=myers",
        "--no-indent-heuristic",
        "--submodule=short",
        *(
            ["--no-patch", "--numstat", "-z"]
            if numstat
            else ["--patch", "--binary", "--full-index"]
        ),
    ]


def diff(
    repo: Path,
    before: str,
    after: str,
    *,
    numstat: bool = False,
    context: int = 3,
    paths: list[str] | None = None,
    pathspecs: list[str] | None = None,
) -> str:
    """Render BEFORE..AFTER, limited to the literal PATHS when given (even empty).

    PATHSPECS are ordinary Git pathspecs, such as globs and :(exclude) patterns.
    """
    if paths is not None and not paths:
        return ""
    return git(
        repo,
        *CONFIG,
        "diff-tree",
        "-r",
        *review_options(numstat, context),
        before,
        after,
        "--",
        *(f":(literal){path}" for path in paths or []),
        *(pathspecs or []),
    )


def diffs(
    repo: Path,
    pairs: list[tuple[str, str]],
    *,
    numstat: bool = False,
    context: int = 3,
    pathspecs: list[str] | None = None,
) -> list[str]:
    """Render each (BEFORE, AFTER) pair exactly as diff would."""
    return diff_pairs(
        repo, pairs, *review_options(numstat, context), pathspecs=pathspecs
    )


def diff_pairs(
    repo: Path,
    pairs: list[tuple[str, str]],
    *options: str,
    pathspecs: list[str] | None = None,
) -> list[str]:
    """Run git diff-tree OPTIONS on every pair through one process.

    Starting a Git process costs several milliseconds, which dominated viewing
    long histories one diff at a time. With --stdin, diff-tree echoes each
    input line of two trees before that pair's output, even when it is empty.
    """
    if not pairs:
        return []
    trees = tree_ids(repo, sorted({revision for pair in pairs for revision in pair}))
    headers = [f"{trees[before]} {trees[after]}\n" for before, after in pairs]
    output = git(
        repo,
        *CONFIG,
        "diff-tree",
        "--stdin",
        "-r",
        *options,
        "--",
        *(pathspecs or []),
        input_text="".join(headers),
    )
    results, position = [], 0
    for index, header in enumerate(headers):
        if not output.startswith(header, position):
            raise click.ClickException("Unexpected output from git diff-tree.")
        start = position + len(header)
        position = (
            next_header(output, headers[index + 1], start)
            if index + 1 < len(headers)
            else len(output)
        )
        results.append(output[start:position])
    return results


def next_header(output: str, header: str, start: int) -> int:
    """Find HEADER where a line or NUL-terminated record could begin.

    Patch lines carry a prefix and paths cannot contain NUL, so output never
    contains a bare line of two object IDs.
    """
    position = start
    while (position := output.find(header, position)) >= 0:
        if position == start or output[position - 1] in "\n\0":
            return position
        position += 1
    raise click.ClickException("Unexpected output from git diff-tree.")


def tree_ids(repo: Path, revisions: list[str]) -> dict[str, str]:
    """Peel each revision to its tree through one process."""
    output = git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        input_text="".join(f"{revision}^{{tree}}\n" for revision in revisions),
    ).splitlines()
    trees = {}
    for revision, line in zip(revisions, output, strict=True):
        oid, _, kind = line.partition(" ")
        if kind != "tree":
            raise click.ClickException(f"Not a tree-ish: {revision}")
        trees[revision] = oid
    return trees


def line_count(text: str) -> int:
    """Count Git's newline-delimited output, including all headers and context."""
    return text.count("\n") + int(bool(text) and not text.endswith("\n"))


def changed_paths(repo: Path, before: str, after: str) -> set[str]:
    """Every file path whose entry differs, without rename detection."""
    output = git(repo, "diff", "--name-only", "-z", "--no-renames", before, after, "--")
    return {path for path in output.split("\0") if path}


def pathspecs(include: tuple[str, ...], exclude: tuple[str, ...]) -> list[str] | None:
    """Combine view filters into Git pathspecs; None means every file."""
    if not include and not exclude:
        return None
    return [*include, *(f":(exclude){pattern}" for pattern in exclude)]


def empty_tree(repo: Path) -> str:
    """The empty tree's ID in this repository's object format."""
    return git(repo, "hash-object", "-t", "tree", "--stdin", input_text="").strip()


def churn(repo: Path, before: str, after: str, paths: list[str] | None = None) -> dict:
    return tally(diff(repo, before, after, numstat=True, paths=paths))


def tally(numstat: str) -> dict:
    """Sum -z numstat output; binary files have no line counts."""
    added = deleted = binary = 0
    for entry in numstat.split("\0"):
        if not entry:
            continue
        plus, minus, _ = entry.split("\t", 2)
        if plus == "-":
            binary += 1
        else:
            added += int(plus)
            deleted += int(minus)
    return {"added": added, "deleted": deleted, "binary_files": binary}


class Commit(NamedTuple):
    parents: list[str]
    author: str
    date: str
    message: str


def log(repo: Path, *revisions: str) -> dict[str, Commit]:
    """The first-parent commits REVISIONS select, oldest first, from one process."""
    fields = git(
        repo,
        "log",
        "--first-parent",
        "--reverse",
        "--no-show-signature",
        "--format=%H%x00%P%x00%an%x00%as%x00%B%x00",
        *revisions,
        "--",
    ).split("\0")
    commits = {}
    for index in range(0, len(fields) - 1, 5):
        oid, parents, author, date, message = fields[index : index + 5]
        # Each record after the first starts on a new line.
        commits[oid.lstrip("\n")] = Commit(
            parents.split(), author, date, message.strip()
        )
    return commits

"""Small Git boundary; all review diffs use the same rendering settings."""

import os
import subprocess
from pathlib import Path

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
    options = (
        ["--no-patch", "--numstat", "-z"]
        if numstat
        else ["--patch", "--binary", "--full-index"]
    )
    return git(
        repo,
        "-c",
        "core.quotePath=true",
        "-c",
        "diff.suppressBlankEmpty=false",
        "diff",
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
        *options,
        before,
        after,
        "--",
        *(f":(literal){path}" for path in paths or []),
        *(pathspecs or []),
    )


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
    added = deleted = binary = 0
    for entry in diff(repo, before, after, numstat=True, paths=paths).split("\0"):
        if not entry:
            continue
        plus, minus, _ = entry.split("\t", 2)
        if plus == "-":
            binary += 1
        else:
            added += int(plus)
            deleted += int(minus)
    return {"added": added, "deleted": deleted, "binary_files": binary}

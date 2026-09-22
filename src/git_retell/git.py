"""Small Git boundary; all review diffs use the same rendering settings."""

import subprocess
from pathlib import Path

import click


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        capture_output=True,
        check=False,
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
    repo: Path, before: str, after: str, *, numstat: bool = False, context: int = 3
) -> str:
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
    )


def line_count(text: str) -> int:
    """Count Git's newline-delimited output, including all headers and context."""
    return text.count("\n") + int(bool(text) and not text.endswith("\n"))


def churn(repo: Path, before: str, after: str) -> dict:
    added = deleted = binary = 0
    for entry in diff(repo, before, after, numstat=True).split("\0"):
        if not entry:
            continue
        plus, minus, _ = entry.split("\t", 2)
        if plus == "-":
            binary += 1
        else:
            added += int(plus)
            deleted += int(minus)
    return {"added": added, "deleted": deleted, "binary_files": binary}

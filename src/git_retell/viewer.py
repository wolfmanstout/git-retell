"""A terminal slideshow: never silently crop or page a step's diff."""

import shutil
import sys
import unicodedata

import click

from .git import diff
from .history import History, inspect


def safe_text(text: str) -> str:
    """Make terminal controls visible; repository contents are untrusted text."""
    return "".join(c if c in "\n\t" or not unicodedata.category(c).startswith("C")
                   else f"\\x{ord(c):02x}" for c in text).expandtabs(8)


def slide(history: History, commits: list[str], index: int) -> str:
    commit = commits[index]
    previous = history.base if index == 0 else commits[index - 1]
    heading = f"SYNTHETIC explanatory history · {history.name} · {index + 1}/{len(commits)} · {commit[:8]}"
    message = safe_text(history.message(commit))
    patch = safe_text(diff(history.repo, previous, commit))
    return f"{heading}\n\n{message}\n\n{patch}\n[←/p] previous   [→/n/space] next   [q] quit"


def dimensions(text: str) -> tuple[int, int]:
    lines = text.split("\n")
    widths = [sum(0 if unicodedata.combining(c) else
                  2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
                  for c in line) for line in lines]
    return max(widths, default=0), len(lines)


def wrap_lines(text: str, columns: int) -> str:
    wrapped = []
    for line in text.split("\n"):
        part, width = "", 0
        for char in line:
            size, _ = dimensions(char)
            if width + size > columns and part:
                wrapped.append(part)
                part, width = "", 0
            part += char
            width += size
        wrapped.append(part)
    return "\n".join(wrapped)


def view(history: History) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise click.ClickException("view needs a terminal. Use show NAME --all for plain output.")
    commits = history.commits()
    if not commits:
        raise click.ClickException("No explanatory steps yet. Create commits in the authoring worktree.")
    report = inspect(history)
    status = "VALID" if report["valid"] else "UNFINISHED / INVALID — run validate for details"
    index = 0
    while True:
        content = status + "\n" + slide(history, commits, index)
        terminal = shutil.get_terminal_size()
        content = wrap_lines(content, max(1, terminal.columns - 1))
        width, height = dimensions(content)
        click.clear()
        if width >= terminal.columns or height >= terminal.lines:
            click.echo(f"SYNTHETIC step {index + 1}/{len(commits)} needs at least "
                       f"{height + 1} rows at {terminal.columns} columns.\n"
                       "Enlarge the terminal, shorten the message, or split the step.\n"
                       "[r] retry   [p/n] previous/next   [q] quit; show prints the full slide.")
        else:
            click.echo(content)
        key = click.getchar()
        if key.lower() == "q" or key == "\x1b":
            return
        if key in ("n", " ", "\x1b[C", "\x1bOB"):
            index = min(index + 1, len(commits) - 1)
        elif key in ("p", "\x1b[D", "\x1bOD"):
            index = max(0, index - 1)

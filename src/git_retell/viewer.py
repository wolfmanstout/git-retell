"""A terminal slideshow: browse complete diffs with adjustable context and paging."""

import shutil
import sys
import unicodedata

import click

from .git import diff
from .retelling import Retelling, inspect


def safe_text(text: str) -> str:
    """Make terminal controls visible; repository contents are untrusted text."""
    return "".join(
        c
        if c in "\n\t" or not unicodedata.category(c).startswith("C")
        else f"\\x{ord(c):02x}"
        for c in text
    ).expandtabs(8)


def slide(
    retelling: Retelling,
    commits: list[str],
    index: int,
    *,
    context: int | None = None,
) -> str:
    context = retelling.context if context is None else context
    commit = commits[index]
    previous = retelling.base if index == 0 else commits[index - 1]
    heading = f"SYNTHETIC explanatory retelling · {retelling.name} · {index + 1}/{len(commits)} · {commit[:8]}"
    message = safe_text(retelling.message(commit))
    patch = safe_text(diff(retelling.repo, previous, commit, context=context))
    return f"{heading}\n\n{message}\n\n{patch}"


def dimensions(text: str) -> tuple[int, int]:
    lines = text.split("\n")
    widths = [
        sum(
            0
            if unicodedata.combining(c)
            else 2
            if unicodedata.east_asian_width(c) in ("W", "F")
            else 1
            for c in line
        )
        for line in lines
    ]
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


def page(
    content: str, label: str, offset: int, columns: int, rows: int
) -> tuple[str, int, int, int]:
    """Reserve fixed chrome and page every wrapped content line, including messages."""
    width = max(1, columns - 1)
    lines = wrap_lines(content, width).split("\n")
    digits = len(str(len(lines)))
    controls = "n/p:step j/k:line f/b:page +/-:context 0:reset q:quit"

    def footer(first: int, last: int) -> list[str]:
        location = f"{first:>{digits}}-{last:>{digits}}/{len(lines)}"
        return wrap_lines(f"{label} {location}\n{controls}", width).split("\n")

    chrome = footer(1, len(lines))
    if len(chrome) > rows - 2:
        # Tiny terminals still show content; full key help remains in --help.
        chrome = [f"{label} q:quit"[:width]]
    height = max(1, rows - len(chrome) - 1)
    offset = max(0, min(offset, max(0, len(lines) - height)))
    visible = lines[offset : offset + height]
    if len(chrome) > 1:
        chrome = footer(offset + 1, offset + len(visible))
    frame = visible + [""] * (height - len(visible)) + chrome
    return "\n".join(frame), offset, height, max(0, len(lines) - height)


def view(retelling: Retelling, context: int | None = None) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise click.ClickException(
            "view needs a terminal. Use show NAME --all for plain output."
        )
    commits = retelling.commits()
    if not commits:
        raise click.ClickException(
            "No explanatory steps yet. Create commits in the authoring worktree."
        )
    initial_context = retelling.context if context is None else context
    index, context, offset = 0, initial_context, 0
    status = ""
    validated_context = None
    cached = None
    content = ""
    while True:
        if validated_context != context:
            status = (
                "VALID" if inspect(retelling, context=context)["valid"] else "INVALID"
            )
            validated_context = context
        if cached != (index, context):
            content = slide(retelling, commits, index, context=context)
            cached = (index, context)
        terminal = shutil.get_terminal_size()
        label = f"{status} {index + 1}/{len(commits)} U{context}"
        frame, offset, height, bottom = page(
            content, label, offset, terminal.columns, terminal.lines
        )
        click.clear()
        click.echo(frame)
        key = click.getchar()
        if key.lower() == "q" or key == "\x1b":
            return
        old_index, old_context = index, context
        if key in ("n", "\x1b[C", "\x1bOC") or (key == " " and offset == bottom):
            index = min(index + 1, len(commits) - 1)
        elif key in ("p", "\x1b[D", "\x1bOD"):
            index = max(0, index - 1)
        elif key in ("j", "\x1b[B", "\x1bOB"):
            offset += 1
        elif key in ("k", "\x1b[A", "\x1bOA"):
            offset -= 1
        elif key in ("f", " ", "\x1b[6~"):
            offset += height
        elif key in ("b", "\x1b[5~"):
            offset -= height
        elif key == "g":
            offset = 0
        elif key == "G":
            offset = bottom
        elif key in ("+", "="):
            context += 3
        elif key == "-":
            context = max(0, context - 3)
        elif key == "0":
            context = initial_context
        if (index, context) != (old_index, old_context):
            offset = 0

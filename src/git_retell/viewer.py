"""A terminal slideshow: browse complete diffs with adjustable context and paging."""

import shutil
import sys
import unicodedata

import click

from .git import diff
from .history import History
from .retelling import Retelling, inspect

# Viewers show a retelling's synthetic steps or a range of real commits.
Story = Retelling | History


def safe_text(text: str) -> str:
    """Make terminal controls visible; repository contents are untrusted text."""
    return "".join(
        c
        if c in "\n\t" or not unicodedata.category(c).startswith("C")
        else f"\\x{ord(c):02x}"
        for c in text
    ).expandtabs(8)


def slide(
    retelling: Story,
    commits: list[str],
    index: int,
    *,
    context: int | None = None,
    pathspecs: list[str] | None = None,
) -> str:
    context = retelling.context if context is None else context
    commit = commits[index]
    previous = retelling.base if index == 0 else commits[index - 1]
    position = f"{index + 1}/{len(commits)} · {commit[:8]}"
    if isinstance(retelling, History):
        author, date = retelling.byline(commit)
        heading = f"History · {retelling.label} · {position} · {author} · {date}"
    else:
        kind = "partial retelling" if retelling.partial else "retelling"
        heading = f"SYNTHETIC explanatory {kind} · {retelling.name} · {position}"
    message = safe_text(retelling.message(commit))
    patch = safe_text(
        diff(retelling.repo, previous, commit, context=context, pathspecs=pathspecs)
    )
    if pathspecs is not None:
        heading += " · filtered"
        patch = patch or "(No changes to the selected files in this step.)\n"
    return f"{heading}\n\n{message}\n\n{patch}"


def selected_steps(retelling: Story, pathspecs: list[str] | None) -> list[int]:
    """Indices of the steps that change any selected file."""
    commits = retelling.commits()
    if pathspecs is None:
        return list(range(len(commits)))
    parents = [retelling.base, *commits[:-1]]
    return [
        index
        for index, (previous, commit) in enumerate(zip(parents, commits))
        if diff(retelling.repo, previous, commit, numstat=True, pathspecs=pathspecs)
    ]


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


def view(
    retelling: Story,
    context: int | None = None,
    pathspecs: list[str] | None = None,
) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise click.ClickException(
            "view needs a terminal. Use show --all for plain output."
        )
    commits = retelling.commits()
    if not commits:
        raise click.ClickException(
            "No explanatory steps yet. Create commits in the authoring worktree."
        )
    # Filtered views skip steps that change none of the selected files.
    steps = selected_steps(retelling, pathspecs)
    if not steps:
        raise click.ClickException("No step changes the selected files.")
    initial_context = retelling.context if context is None else context
    position, context, offset = 0, initial_context, 0
    status = ""
    validated_context = None
    cached = None
    content = ""
    while True:
        if validated_context != context and isinstance(retelling, Retelling):
            status = (
                "VALID " if inspect(retelling, context=context)["valid"] else "INVALID "
            )
            validated_context = context
        index = steps[position]
        if cached != (index, context):
            content = slide(
                retelling, commits, index, context=context, pathspecs=pathspecs
            )
            cached = (index, context)
        terminal = shutil.get_terminal_size()
        label = f"{status}{index + 1}/{len(commits)} U{context}"
        if pathspecs is not None:
            label += f" filtered {position + 1}/{len(steps)}"
        frame, offset, height, bottom = page(
            content, label, offset, terminal.columns, terminal.lines
        )
        click.clear()
        click.echo(frame)
        key = click.getchar()
        if key.lower() == "q" or key == "\x1b":
            return
        old_position, old_context = position, context
        if key in ("n", "\x1b[C", "\x1bOC") or (key == " " and offset == bottom):
            position = min(position + 1, len(steps) - 1)
        elif key in ("p", "\x1b[D", "\x1bOD"):
            position = max(0, position - 1)
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
        if (position, context) != (old_position, old_context):
            offset = 0

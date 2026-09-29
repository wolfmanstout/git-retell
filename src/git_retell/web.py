"""A browser slideshow: every line keeps one identity so transitions can animate it.

Each file version is a list of line IDs. A step's unchanged lines keep their IDs
and its added lines get new ones, so any two slides can be compared by ID. The
browser uses this to collapse, move, recolor, and expand lines between slides.
"""

import html
import json
import re
import subprocess
import tempfile
import webbrowser
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

import click
from pygments.lexers import get_lexer_for_filename
from pygments.token import (
    Comment,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    String,
    _TokenType,
)
from pygments.util import ClassNotFound

from .git import git
from .retelling import Retelling, inspect
from .viewer import safe_text

EMPTY = "0" * 40
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
# Hyphenated tokens (Co-Authored-By) or well-known words; "Note: ..." stays prose.
TRAILER = re.compile(r"(?i:[a-z0-9]+(?:-[a-z0-9]+)+|fixes|closes|refs|cc|bug): \S")
# Coarse token classes keep the payload small and the theme easy to restyle.
CATEGORIES: list[tuple[_TokenType, str]] = [
    (Comment, "c"),
    (String, "s"),
    (Number, "n"),
    (Keyword, "k"),
    (Name.Function, "f"),
    (Name.Class, "t"),
    (Name.Decorator, "d"),
    (Name.Builtin, "b"),
    (Name.Tag, "g"),
    (Name.Attribute, "a"),
    (Operator.Word, "k"),
    (Operator, "o"),
    (Generic.Heading, "h"),
    (Generic.Subheading, "h"),
    (Generic.Emph, "e"),
    (Generic.Strong, "h"),
]


def blobs(repo: Path, ids: set[str]) -> dict[str, bytes]:
    """Read many blobs through one cat-file process."""
    ids = {i for i in ids if i != EMPTY}
    if not ids:
        return {}
    order = sorted(ids)
    output = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{i}\n" for i in order).encode(),
        capture_output=True,
        check=True,
    ).stdout
    found, position = {}, 0
    for oid in order:
        end = output.index(b"\n", position)
        header = output[position:end].split()
        position = end + 1
        if len(header) < 3 or header[1] == b"missing":
            found[oid] = b""
            continue
        size = int(header[2])
        found[oid] = output[position : position + size]
        position += size + 1
    return found


def without_trailers(body: str) -> str:
    """Drop a final paragraph of Git trailers such as Co-Authored-By; slides show prose."""
    paragraphs = body.strip().split("\n\n")
    last = paragraphs[-1].split("\n")
    # Folded trailer values continue on indented lines.
    if TRAILER.match(last[0]) and all(
        TRAILER.match(line) or line[:1].isspace() for line in last
    ):
        paragraphs.pop()
    return "\n\n".join(paragraphs).strip()


def split_lines(text: str) -> list[str]:
    lines = text.split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def category(token: _TokenType) -> str:
    for kind, name in CATEGORIES:
        if token in kind:
            return name
    return ""


def highlight(path: str, text: str) -> list[str] | None:
    """Highlight a whole file version so multi-line strings and comments color correctly."""
    try:
        lexer = get_lexer_for_filename(
            path, stripnl=False, ensurenl=False, stripall=False
        )
    except ClassNotFound:
        return None
    lines, current = [], ""
    try:
        for token, value in lexer.get_tokens(text):
            name = category(token)
            for index, part in enumerate(value.split("\n")):
                if index:
                    lines.append(current)
                    current = ""
                if part:
                    escaped = html.escape(part, quote=False)
                    current += f'<i class="{name}">{escaped}</i>' if name else escaped
    except Exception:
        return None
    lines.append(current)
    expected = split_lines(text)
    lines = lines[: len(expected)]
    # Lexers occasionally normalize text; never show highlighted text that differs.
    return lines if len(lines) == len(expected) else None


class Builder:
    """Accumulate line texts, file versions, and slides for the browser payload."""

    def __init__(self, retelling: Retelling):
        self.retelling = retelling
        self.text: list[str] = []
        self.html: list[str | None] = []
        self.versions: list[list[int]] = []
        # Current line IDs of each file path, by version index.
        self.current: dict[str, int] = {}

    def lines_for(self, oid: str, content: dict[str, bytes], mode: str) -> list[str]:
        if oid == EMPTY:
            return []
        if mode == "160000":
            return [f"Subproject commit {oid}"]
        return split_lines(safe_text(content[oid].decode("utf-8", errors="replace")))

    def new_version(
        self, path: str, lines: list[str], ids: Sequence[int | None]
    ) -> int:
        """Store IDs, minting new ones for None; highlight lines not yet seen."""
        colored = highlight(path, "\n".join(lines) + "\n") if lines else None
        result = []
        for number, (line, identity) in enumerate(zip(lines, ids, strict=True)):
            if identity is None:
                identity = len(self.text)
                self.text.append(line)
                self.html.append(None)
            if self.html[identity] is None and colored is not None:
                self.html[identity] = colored[number]
            result.append(identity)
        self.versions.append(result)
        return len(self.versions) - 1

    def matched(self, before: str, after: str, old_ids: list[int], new_count: int):
        """Carry IDs of unchanged lines through Git's own line matching."""
        patch = git(
            self.retelling.repo,
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--unified=0",
            "--diff-algorithm=myers",
            "--no-indent-heuristic",
            before,
            after,
        )
        ids: list[int | None] = []
        old = 0
        for match in HUNK.finditer(patch):
            start, count, new_start, new_count_hunk = (
                int(match[1]),
                int(match[2] or 1),
                int(match[3]),
                int(match[4] or 1),
            )
            # Zero-length ranges name the line before the change.
            unchanged_until = start - 1 if count else start
            new_unchanged = (new_start - 1 if new_count_hunk else new_start) - len(ids)
            ids.extend(old_ids[old : old + new_unchanged])
            old = unchanged_until + count
            ids.extend([None] * new_count_hunk)
        ids.extend(old_ids[old:])
        if len(ids) != new_count:
            return [None] * new_count
        return ids

    def step(self, previous: str, commit: str, content: dict[str, bytes], raw):
        files = []
        numstat = numstats(self.retelling.repo, previous, commit)
        for old_mode, new_mode, old_oid, new_oid, status, path in raw:
            plus, minus = numstat.get(path, ("0", "0"))
            binary = plus == "-"
            entry = {
                "path": path,
                "status": status,
                "oldMode": old_mode,
                "newMode": new_mode,
                "binary": binary,
                "added": 0 if binary else int(plus),
                "deleted": 0 if binary else int(minus),
            }
            if binary:
                self.current.pop(path, None)
            else:
                old_lines = self.lines_for(old_oid, content, old_mode)
                new_lines = self.lines_for(new_oid, content, new_mode)
                if path not in self.current or len(
                    self.versions[self.current[path]]
                ) != len(old_lines):
                    self.current[path] = self.new_version(
                        path, old_lines, [None] * len(old_lines)
                    )
                before = self.current[path]
                if new_oid == EMPTY:
                    ids = []
                elif old_oid == EMPTY or old_mode == "160000" or new_mode == "160000":
                    ids = [None] * len(new_lines)
                else:
                    ids = self.matched(
                        old_oid, new_oid, self.versions[before], len(new_lines)
                    )
                after = self.new_version(path, new_lines, ids)
                self.current[path] = after
                entry.update(before=before, after=after)
            files.append(entry)
        return files


def raw_changes(repo: Path, before: str, after: str) -> list[tuple[str, ...]]:
    fields = git(
        repo, "diff", "--raw", "-z", "--no-abbrev", "--no-renames", before, after, "--"
    ).split("\0")
    changes = []
    for header, path in zip(fields[0::2], fields[1::2], strict=False):
        if not header:
            continue
        old_mode, new_mode, old_oid, new_oid, status = header.lstrip(":").split()
        changes.append((old_mode, new_mode, old_oid, new_oid, status, path))
    return changes


def numstats(repo: Path, before: str, after: str) -> dict[str, tuple[str, str]]:
    result = {}
    output = git(
        repo, "diff", "--numstat", "-z", "--no-renames", before, after, "--"
    ).split("\0")
    for entry in output:
        if entry:
            plus, minus, path = entry.split("\t", 2)
            result[path] = (plus, minus)
    return result


def payload(retelling: Retelling, context: int | None = None) -> dict:
    context = retelling.context if context is None else context
    commits = retelling.commits()
    if not commits:
        raise click.ClickException(
            "No explanatory steps yet. Create commits in the authoring worktree."
        )
    report = inspect(retelling, context=context)
    parents = [retelling.base, *commits[:-1]]
    changes = [raw_changes(retelling.repo, a, b) for a, b in zip(parents, commits)]
    content = blobs(
        retelling.repo,
        {oid for step in changes for change in step for oid in change[2:4]},
    )
    builder = Builder(retelling)
    slides = []
    for number, (previous, commit, raw) in enumerate(
        zip(parents, commits, changes, strict=True)
    ):
        message = safe_text(retelling.message(commit))
        subject, _, body = message.partition("\n")
        slides.append(
            {
                "commit": commit,
                "subject": subject,
                "body": without_trailers(body),
                "lines": report["steps"][number]["presentation_lines"],
                "files": builder.step(previous, commit, content, raw),
            }
        )
    return {
        "name": retelling.name,
        "base": retelling.base,
        "target": retelling.target,
        "valid": report["valid"],
        "issues": report["issues"],
        "budget": retelling.budget,
        "context": context,
        "expansion": report["expansion_factor"],
        "slides": slides,
        "versions": builder.versions,
        "text": builder.text,
        "html": builder.html,
    }


def page(data: dict) -> str:
    template = resources.files("git_retell").joinpath("web.html").read_text("utf-8")
    # Escape markup-significant characters so repository text cannot end the script.
    encoded = (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    title = html.escape(f"{data['name']} · git-retell")
    return template.replace("__TITLE__", title).replace("__DATA__", encoded)


def web(
    retelling: Retelling,
    output: Path | None = None,
    open_browser: bool = True,
    context: int | None = None,
) -> Path:
    document = page(payload(retelling, context))
    if output is None:
        directory = Path(tempfile.mkdtemp(prefix="git-retell-"))
        output = directory / f"{retelling.name}.html"
    output.write_text(document, encoding="utf-8")
    if open_browser:
        webbrowser.open(output.resolve().as_uri())
    return output

"""Commit messages: the prose a step shows and the trailers that structure it."""

import re

# Hyphenated tokens (Co-Authored-By) or well-known words; "Note: ..." stays prose.
# Chapter may be empty so validate can warn about it rather than show it as prose.
TRAILER = re.compile(
    r"(?i:(?:[a-z0-9]+(?:-[a-z0-9]+)+|fixes|closes|refs|cc|bug): \S|chapter:)"
)
CHAPTER = re.compile(r"(?i)chapter:(.*)")


def trailer_block(body: str) -> tuple[str, list[str]]:
    """Split the trailing paragraphs of trailers such as Co-Authored-By from the prose.

    Git reads only the last paragraph as trailers, but authors often set a
    Chapter trailer apart from Co-Authored-By with a blank line, so every
    trailing paragraph made only of trailers counts.
    """
    paragraphs = body.strip().split("\n\n")
    trailers: list[str] = []
    while paragraphs and is_trailers(lines := paragraphs[-1].split("\n")):
        paragraphs.pop()
        trailers = lines + trailers
    return "\n\n".join(paragraphs).strip(), trailers


def is_trailers(lines: list[str]) -> bool:
    # Folded trailer values continue on indented lines.
    return bool(TRAILER.match(lines[0])) and all(
        TRAILER.match(line) or line[:1].isspace() for line in lines
    )


def without_trailers(body: str) -> str:
    """The body without its trailers; slides show prose."""
    return trailer_block(body)[0]


def chapter_titles(message: str) -> list[str]:
    """The values of every Chapter trailer, in order, including empty ones."""
    lines = trailer_block(message.partition("\n")[2])[1]
    return [m[1].strip() for line in lines if (m := CHAPTER.match(line))]


def stray_chapters(message: str) -> int:
    """How many Chapter lines sit in the prose, where they start nothing."""
    prose = trailer_block(message.partition("\n")[2])[0]
    return sum(bool(CHAPTER.match(line)) for line in prose.split("\n"))


def chapter(message: str) -> str | None:
    """The title of the chapter this step starts, if any."""
    return next((title for title in chapter_titles(message) if title), None)


def chapters(messages: list[str]) -> list[tuple[int, str] | None]:
    """Each step's chapter as (number from 1, title); None before the first."""
    current, number, result = None, 0, []
    for message in messages:
        if (title := chapter(message)) is not None:
            number += 1
            current = (number, title)
        result.append(current)
    return result

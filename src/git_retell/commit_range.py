"""Real commits shown like a retelling's steps, for reading a branch commit by commit."""

from dataclasses import dataclass, field
from pathlib import Path

import click

from .git import Commit, empty_tree, log, resolve


@dataclass
class CommitRange:
    """The first-parent chain of commits reachable from a tip but not from a base.

    Each commit is a step against the one before it. The diff base is the
    parent of the oldest commit (the empty tree for a root commit), so a
    branch reads from where it forked even if the base branch moved on.
    Nothing is pinned or validated; the final commit is the target.
    """

    repo: Path
    label: str
    base: str
    tip: str
    # Each step's commit details, oldest first.
    history: dict[str, Commit] = field(repr=False)
    context: int = 3

    @property
    def target(self) -> str:
        return self.tip

    @classmethod
    def load(
        cls, repo: Path, base: str | None, target: str, label: str
    ) -> "CommitRange":
        tip = resolve(repo, target)
        since = [] if base is None else [f"^{resolve(repo, base)}"]
        history = log(repo, tip, *since)
        if not history:
            raise click.ClickException(f"No commits in {label}.")
        parents = next(iter(history.values())).parents
        start = parents[0] if parents else empty_tree(repo)
        return cls(repo, label, start, tip, history)

    def commits(self) -> list[str]:
        return list(self.history)

    def message(self, commit: str) -> str:
        return self.history[commit].message

    def byline(self, commit: str) -> tuple[str, str]:
        """The author's name and the authored date."""
        found = self.history[commit]
        return found.author, found.date

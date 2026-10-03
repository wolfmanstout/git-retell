"""Real commits shown like a retelling's steps, for reading a branch commit by commit."""

from dataclasses import dataclass, field
from pathlib import Path

import click

from .git import empty_tree, git, resolve


@dataclass
class History:
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
    steps: list[str] = field(default_factory=list)
    context: int = 3

    @property
    def target(self) -> str:
        return self.tip

    @classmethod
    def load(cls, repo: Path, base: str | None, target: str, label: str) -> "History":
        tip = resolve(repo, target)
        since = [] if base is None else [f"^{resolve(repo, base)}"]
        steps = git(
            repo, "rev-list", "--first-parent", "--reverse", tip, *since, "--"
        ).splitlines()
        if not steps:
            raise click.ClickException(f"No commits in {label}.")
        parents = git(repo, "show", "-s", "--format=%P", steps[0]).split()
        start = parents[0] if parents else empty_tree(repo)
        return cls(repo, label, start, tip, steps)

    def commits(self) -> list[str]:
        return self.steps

    def message(self, commit: str) -> str:
        return git(self.repo, "show", "-s", "--format=%B", commit).strip()

    def byline(self, commit: str) -> tuple[str, str]:
        """The author's name and the authored date."""
        name, _, date = (
            git(self.repo, "show", "-s", "--format=%an%x00%as", commit)
            .strip()
            .partition("\0")
        )
        return name, date

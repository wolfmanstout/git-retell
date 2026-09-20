"""Git refs pin the endpoints; the explanatory artifact is a normal branch."""

from dataclasses import dataclass
from pathlib import Path
import re

import click

from .git import churn, diff, git, line_count, resolve


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise click.ClickException("Use a name starting with a-z, then a-z, 0-9 or hyphens.")
    return name


@dataclass
class History:
    repo: Path
    name: str
    base: str
    target: str
    tip: str
    budget: int

    @classmethod
    def load(cls, repo: Path, name: str) -> "History":
        validate_name(name)
        prefix = f"refs/retell/{name}"
        budget = int(git(repo, "config", "--get", f"retell.{name}.budget"))
        return cls(repo, name, resolve(repo, f"{prefix}/base"),
                   resolve(repo, f"{prefix}/target"),
                   resolve(repo, f"refs/heads/retell/{name}"), budget)

    def commits(self) -> list[str]:
        return git(self.repo, "rev-list", "--first-parent", "--reverse",
                   f"{self.base}..{self.tip}").splitlines()

    def message(self, commit: str) -> str:
        return git(self.repo, "show", "-s", "--format=%B", commit).strip()


def start(repo: Path, name: str, base: str, target: str, path: Path, budget: int) -> History:
    validate_name(name)
    before, after = resolve(repo, base), resolve(repo, target)
    prefix = f"refs/retell/{name}"
    if git(repo, "for-each-ref", "--format=%(refname)", prefix).strip():
        raise click.ClickException(f"History {name!r} already exists.")
    git(repo, "worktree", "add", "-b", f"retell/{name}", str(path), before)
    git(repo, "update-ref", f"{prefix}/base", before)
    git(repo, "update-ref", f"{prefix}/target", after)
    git(repo, "config", f"retell.{name}.budget", str(budget))
    return History.load(repo, name)


def inspect(history: History, budget: int | None = None) -> dict:
    limit = history.budget if budget is None else budget
    issues: list[str] = []
    steps: list[dict] = []
    previous = history.base
    for number, commit in enumerate(history.commits(), 1):
        parents = git(history.repo, "show", "-s", "--format=%P", commit).split()
        if parents != [previous]:
            issues.append(f"Step {number} must have exactly the preceding commit as its parent.")
        patch = diff(history.repo, previous, commit)
        size = line_count(patch)
        if size > limit:
            issues.append(f"Step {number}: {size} presentation lines exceeds budget {limit}.")
        steps.append({"step": number, "commit": commit,
                      "subject": history.message(commit).split("\n")[0],
                      "presentation_lines": size, **churn(history.repo, previous, commit)})
        previous = commit
    return finish_report(history, limit, issues, steps, previous)


def finish_report(history: History, limit: int, issues: list[str],
                  steps: list[dict], previous: str) -> dict:
    base_tree = resolve(history.repo, history.base, "tree")
    target_tree = resolve(history.repo, history.target, "tree")
    tip_tree = resolve(history.repo, history.tip, "tree")
    if previous != history.tip:
        issues.append("The synthetic branch does not begin at the pinned base commit.")
    if tip_tree != target_tree:
        issues.append("Final tree differs from the pinned target tree; history is unfinished.")
    real = churn(history.repo, history.base, history.target)
    real_size = real["added"] + real["deleted"]
    synthetic_size = sum(s["added"] + s["deleted"] for s in steps)
    has_binary = real["binary_files"] or any(s["binary_files"] for s in steps)
    expansion = synthetic_size / real_size if real_size and not has_binary else None
    return {"name": history.name, "synthetic": True, "valid": not issues,
            "base": history.base, "target": history.target, "tip": history.tip,
            "base_tree": base_tree, "target_tree": target_tree, "tip_tree": tip_tree,
            "budget": limit, "step_count": len(steps), "steps": steps,
            "real_churn": real_size, "synthetic_churn": synthetic_size,
            "real_presentation_lines": line_count(diff(history.repo, history.base, history.target)),
            "total_presentation_lines": sum(s["presentation_lines"] for s in steps),
            "expansion_factor": expansion,
            "expansion_note": "Undefined for zero real churn or binary changes." if expansion is None else None,
            "issues": issues}

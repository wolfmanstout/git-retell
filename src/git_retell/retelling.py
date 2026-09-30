"""Git refs pin the endpoints; the explanatory artifact is a normal branch."""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import click

from .git import churn, diff, git, line_count, resolve


def validate_name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise click.ClickException(
            "Use a name starting with a-z, then a-z, 0-9 or hyphens."
        )
    return name


@dataclass
class Retelling:
    repo: Path
    name: str
    base: str
    target: str
    tip: str
    budget: int
    context: int = 3

    @classmethod
    def load(cls, repo: Path, name: str) -> "Retelling":
        validate_name(name)
        prefix = f"refs/retell/{name}"
        if name not in names(repo):
            raise click.ClickException(
                f"No retelling named {name!r}. Use git-retell list."
            )
        budget = setting(repo, name, "budget", 60, 1)
        return cls(
            repo,
            name,
            resolve(repo, f"{prefix}/base"),
            resolve(repo, f"{prefix}/target"),
            resolve(repo, f"refs/heads/retell/{name}"),
            budget,
            setting(repo, name, "context", 3, 0),
        )

    def commits(self) -> list[str]:
        return git(
            self.repo,
            "rev-list",
            "--first-parent",
            "--reverse",
            f"{self.base}..{self.tip}",
        ).splitlines()

    def message(self, commit: str) -> str:
        return git(self.repo, "show", "-s", "--format=%B", commit).strip()


def start(
    repo: Path,
    name: str,
    base: str,
    target: str,
    path: Path,
    budget: int,
    context: int = 3,
) -> Retelling:
    validate_name(name)
    before, after = resolve(repo, base), resolve(repo, target)
    prefix = f"refs/retell/{name}"
    if git(repo, "for-each-ref", "--format=%(refname)", prefix).strip():
        raise click.ClickException(f"Retelling {name!r} already exists.")
    git(repo, "worktree", "add", "-b", f"retell/{name}", str(path), before)
    git(repo, "update-ref", f"{prefix}/base", before)
    git(repo, "update-ref", f"{prefix}/target", after)
    git(repo, "config", f"retell.{name}.budget", str(budget))
    git(repo, "config", f"retell.{name}.context", str(context))
    return Retelling.load(repo, name)


def inspect(
    retelling: Retelling, budget: int | None = None, *, context: int | None = None
) -> dict:
    limit = retelling.budget if budget is None else budget
    context = retelling.context if context is None else context
    issues: list[str] = []
    steps: list[dict] = []
    previous = retelling.base
    for number, commit in enumerate(retelling.commits(), 1):
        parents = git(retelling.repo, "show", "-s", "--format=%P", commit).split()
        if parents != [previous]:
            issues.append(
                f"Step {number} must have exactly the preceding commit as its parent."
            )
        patch = diff(retelling.repo, previous, commit, context=context)
        size = line_count(patch)
        if size > limit:
            issues.append(
                f"Step {number}: {size} presentation lines exceeds budget {limit}."
            )
        steps.append(
            {
                "step": number,
                "commit": commit,
                "subject": retelling.message(commit).split("\n")[0],
                "presentation_lines": size,
                **churn(retelling.repo, previous, commit),
            }
        )
        previous = commit
    return finish_report(retelling, limit, issues, steps, previous, context)


def finish_report(
    retelling: Retelling,
    limit: int,
    issues: list[str],
    steps: list[dict],
    previous: str,
    context: int,
) -> dict:
    base_tree = resolve(retelling.repo, retelling.base, "tree")
    target_tree = resolve(retelling.repo, retelling.target, "tree")
    tip_tree = resolve(retelling.repo, retelling.tip, "tree")
    if previous != retelling.tip:
        issues.append("The synthetic branch does not begin at the pinned base commit.")
    if tip_tree != target_tree:
        issues.append(
            "Final tree differs from the pinned target tree; retelling is unfinished."
        )
    real = churn(retelling.repo, retelling.base, retelling.target)
    real_size = real["added"] + real["deleted"]
    synthetic_size = sum(s["added"] + s["deleted"] for s in steps)
    has_binary = real["binary_files"] or any(s["binary_files"] for s in steps)
    expansion = synthetic_size / real_size if real_size and not has_binary else None
    return {
        "name": retelling.name,
        "synthetic": True,
        "valid": not issues,
        "base": retelling.base,
        "target": retelling.target,
        "tip": retelling.tip,
        "base_tree": base_tree,
        "target_tree": target_tree,
        "tip_tree": tip_tree,
        "budget": limit,
        "context": context,
        "step_count": len(steps),
        "steps": steps,
        "real_churn": real_size,
        "synthetic_churn": synthetic_size,
        "real_presentation_lines": line_count(
            diff(retelling.repo, retelling.base, retelling.target, context=context)
        ),
        "total_presentation_lines": sum(s["presentation_lines"] for s in steps),
        "expansion_factor": expansion,
        "expansion_note": "Undefined for zero real churn or binary changes."
        if expansion is None
        else None,
        "issues": issues,
    }


def names(repo: Path) -> list[str]:
    """Discover both registered endpoints and synthetic branches, including incomplete entries."""
    refs = git(
        repo,
        "for-each-ref",
        "--format=%(refname)",
        "refs/retell/",
        "refs/heads/retell/",
    )
    found = set()
    for ref in refs.splitlines():
        if ref.startswith("refs/heads/retell/"):
            found.add(ref.removeprefix("refs/heads/retell/"))
        elif ref.endswith(("/base", "/target")):
            found.add(ref.removeprefix("refs/retell/").rsplit("/", 1)[0])
    return sorted(found)


def worktrees(repo: Path, name: str) -> list[dict]:
    attached = []
    for record in git(repo, "worktree", "list", "--porcelain", "-z").split("\0\0"):
        fields = {}
        for field in record.split("\0"):
            if field:
                key, _, value = field.partition(" ")
                fields[key] = value
        if fields.get("branch") == f"refs/heads/retell/{name}":
            attached.append(fields)
    return attached


def check_removable(repo: Path, tree: dict) -> None:
    """Refuse to remove a current, locked, or dirty authoring worktree.

    Ignored files are disposable build output in an authoring worktree, so they
    do not block removal; uncommitted and untracked files might be unsaved work.
    A prunable worktree has no checkout left to inspect.
    """
    path = Path(tree["worktree"])
    if "locked" in tree:
        raise click.ClickException(f"Worktree {path} is locked; unlock it first.")
    if "prunable" in tree:
        return
    if path.resolve() == repo.resolve() or path.resolve() in (
        Path.cwd().resolve(),
        *Path.cwd().resolve().parents,
    ):
        raise click.ClickException(
            f"Cannot remove the current worktree {path}. Run from another checkout."
        )
    if git(path, "status", "--porcelain", "--untracked-files=all").strip():
        raise click.ClickException(
            f"Worktree {path} contains changes/untracked files; "
            "commit, discard, or preserve them first."
        )


def remove_worktrees(repo: Path, attached: list[dict]) -> None:
    """Remove live worktrees; unregister only these entries if already deleted.

    git worktree prune would also drop unrelated stale entries (for example on
    an unmounted drive), so a missing checkout's admin directory is removed
    directly. Any leftover non-Git directory is left on disk.
    """
    for tree in attached:
        if "prunable" not in tree:
            git(repo, "worktree", "remove", tree["worktree"])
            continue
        common = repo / git(repo, "rev-parse", "--git-common-dir").strip()
        for admin in (common / "worktrees").iterdir():
            gitdir = admin / "gitdir"
            if gitdir.is_file() and Path(gitdir.read_text().strip()).parent == Path(
                tree["worktree"]
            ):
                shutil.rmtree(admin)


def finish(repo: Path, name: str) -> tuple[dict, list[str]]:
    """Validate, then remove authoring worktrees only if the retelling is valid."""
    report = inspect(Retelling.load(repo, name))
    if not report["valid"]:
        return report, []
    attached = worktrees(repo, name)
    for tree in attached:
        check_removable(repo, tree)
    remove_worktrees(repo, attached)
    return report, [tree["worktree"] for tree in attached]


def resume(repo: Path, name: str, path: Path) -> Retelling:
    """Check out an existing retelling's branch in a new authoring worktree."""
    retelling = Retelling.load(repo, name)
    attached = worktrees(repo, name)
    if live := [t for t in attached if "prunable" not in t]:
        raise click.ClickException(
            f"Retelling is already checked out at {live[0]['worktree']}."
        )
    for tree in attached:
        check_removable(repo, tree)
    remove_worktrees(repo, attached)
    git(repo, "worktree", "add", str(path), f"retell/{name}")
    return retelling


def delete(repo: Path, name: str) -> list[str]:
    """Delete one retelling's refs/config and remove its authoring worktrees."""
    validate_name(name)
    if name not in names(repo):
        raise click.ClickException(f"No retelling named {name!r}. Use git-retell list.")
    attached = worktrees(repo, name)
    for tree in attached:
        check_removable(repo, tree)
    refs = git(
        repo,
        "for-each-ref",
        "--format=%(refname) %(objectname)",
        f"refs/retell/{name}/",
        f"refs/heads/retell/{name}",
    )
    expected = {
        f"refs/retell/{name}/base",
        f"refs/retell/{name}/target",
        f"refs/heads/retell/{name}",
    }
    commands = [
        f"delete {ref} {oid}"
        for ref, oid in (line.split() for line in refs.splitlines())
        if ref in expected
    ]
    remove_worktrees(repo, attached)
    git(
        repo,
        "update-ref",
        "--stdin",
        input_text="start\n" + "\n".join(commands) + "\nprepare\ncommit\n",
    )
    if any(
        line.startswith(f"retell.{name}.")
        for line in git(repo, "config", "--local", "--list").splitlines()
    ):
        git(repo, "config", "--local", "--remove-section", f"retell.{name}")
    return [tree["worktree"] for tree in attached]


def setting(repo: Path, name: str, key: str, default: int, minimum: int) -> int:
    value = git(
        repo, "config", "--default", str(default), "--get", f"retell.{name}.{key}"
    ).strip()
    try:
        number = int(value)
        if number >= minimum:
            return number
    except ValueError:
        pass
    raise click.ClickException(
        f"Invalid retell.{name}.{key}: expected an integer >= {minimum}, got {value!r}."
    )

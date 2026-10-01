"""Git refs pin the endpoints; the explanatory artifact is a normal branch."""

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import click

from .git import changed_paths, churn, diff, empty_tree, git, line_count, resolve


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
    partial: bool = False

    @classmethod
    def load(cls, repo: Path, name: str) -> "Retelling":
        validate_name(name)
        prefix = f"refs/retell/{name}"
        if name not in names(repo):
            raise click.ClickException(
                f"No retelling named {name!r}. Use git-retell list."
            )
        saved = settings(repo, name)
        return cls(
            repo,
            name,
            resolve(repo, f"{prefix}/base"),
            resolve(repo, f"{prefix}/target"),
            resolve(repo, f"refs/heads/retell/{name}"),
            saved["budget"],
            saved["context"],
            saved["partial"],
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
    base: str | None,
    target: str,
    path: Path,
    budget: int,
    context: int = 3,
    partial: bool = False,
) -> Retelling:
    """Pin endpoints; without a BASE, anchor at an empty root commit instead."""
    validate_name(name)
    after = resolve(repo, target)
    prefix = f"refs/retell/{name}"
    if git(repo, "for-each-ref", "--format=%(refname)", prefix).strip():
        raise click.ClickException(f"Retelling {name!r} already exists.")
    before = resolve(repo, base) if base is not None else empty_root(repo, name)
    git(repo, "worktree", "add", "-b", f"retell/{name}", str(path), before)
    git(repo, "update-ref", f"{prefix}/base", before)
    git(repo, "update-ref", f"{prefix}/target", after)
    save_settings(repo, name, budget=budget, context=context, partial=partial)
    return Retelling.load(repo, name)


def empty_root(repo: Path, name: str) -> str:
    """A parentless commit of the empty tree, so a retelling can build from scratch.

    A fixed identity keeps it working without user.name and marks it as synthetic.
    """
    tree = git(repo, "mktree", input_text="").strip()
    return git(
        repo,
        "-c",
        "user.name=git-retell",
        "-c",
        "user.email=git-retell@invalid",
        "commit-tree",
        tree,
        "-m",
        f"SYNTHETIC empty base for retelling {name}",
    ).strip()


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
    repo, base, target, tip = (
        retelling.repo,
        retelling.base,
        retelling.target,
        retelling.tip,
    )
    base_tree = resolve(repo, base, "tree")
    target_tree = resolve(repo, target, "tree")
    tip_tree = resolve(repo, tip, "tree")
    if previous != tip:
        issues.append("The synthetic branch does not begin at the pinned base commit.")
    # Real churn and size cover only the retold paths: all of them unless partial.
    retold = None
    omitted: list[dict] = []
    if tip_tree != target_tree and not retelling.partial:
        issues.append(
            "Final tree differs from the pinned target tree; retelling is unfinished."
        )
    elif tip_tree != target_tree:
        remaining = changed_paths(repo, tip, target)
        if stray := sorted(remaining & changed_paths(repo, base, tip)):
            issues.append(
                "Partial retelling changes these files without reaching their "
                f"target versions: {', '.join(stray)}"
            )
        retold = sorted(changed_paths(repo, base, target) - remaining)
        omitted = [
            {"path": path, **churn(repo, base, target, [path])}
            for path in sorted(remaining - set(stray))
        ]
    real = churn(repo, base, target, retold)
    real_size = real["added"] + real["deleted"]
    synthetic_size = sum(s["added"] + s["deleted"] for s in steps)
    has_binary = real["binary_files"] or any(s["binary_files"] for s in steps)
    expansion = synthetic_size / real_size if real_size and not has_binary else None
    return {
        "name": retelling.name,
        "synthetic": True,
        "valid": not issues,
        "partial": retelling.partial,
        "from_scratch": base_tree == empty_tree(repo),
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
            diff(repo, base, target, context=context, paths=retold)
        ),
        "total_presentation_lines": sum(s["presentation_lines"] for s in steps),
        "expansion_factor": expansion,
        "expansion_note": "Undefined for zero real churn or binary changes."
        if expansion is None
        else None,
        "omitted_files": omitted,
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
    """Delete one retelling's refs and remove its authoring worktrees."""
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
        f"refs/retell/{name}/settings",
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
    return [tree["worktree"] for tree in attached]


# Each saved setting's default and smallest allowed value (None for booleans).
DEFAULTS: dict[str, tuple[int | bool, int | None]] = {
    "budget": (60, 1),
    "context": (3, 0),
    "partial": (False, None),
}


def settings(repo: Path, name: str) -> dict:
    """Read the JSON settings blob; a missing blob or key uses its default."""
    ref = f"refs/retell/{name}/settings"
    saved = {}
    if git(repo, "for-each-ref", "--format=%(refname)", ref).strip():
        try:
            saved = json.loads(git(repo, "cat-file", "blob", ref))
        except ValueError:
            saved = None
        if not isinstance(saved, dict):
            raise click.ClickException(f"Invalid {ref}: expected a JSON object.")
    result = {}
    for key, (default, minimum) in DEFAULTS.items():
        value = saved.get(key, default)
        if minimum is None:
            if type(value) is not bool:
                raise click.ClickException(
                    f"Invalid {key} in {ref}: expected true or false, got {value!r}."
                )
        elif type(value) is not int or value < minimum:
            raise click.ClickException(
                f"Invalid {key} in {ref}: expected an integer >= {minimum}, got {value!r}."
            )
        result[key] = value
    return result


def save_settings(repo: Path, name: str, **changes: int | bool) -> dict:
    """Store the current settings updated with CHANGES as a new JSON blob."""
    saved = {**settings(repo, name), **changes}
    blob = git(
        repo,
        "hash-object",
        "-t",
        "blob",
        "-w",
        "--stdin",
        input_text=json.dumps(saved, indent=2, sort_keys=True) + "\n",
    ).strip()
    git(repo, "update-ref", f"refs/retell/{name}/settings", blob)
    return saved

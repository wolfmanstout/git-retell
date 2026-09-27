"""One CLI for agents authoring histories and humans reviewing them."""

import json
from pathlib import Path

import click

from . import checks
from .git import root
from .retelling import Retelling, inspect, names, worktrees
from .retelling import delete as delete_retelling
from .retelling import start as start_retelling
from .viewer import slide
from .viewer import view as view_retelling


@click.group()
@click.version_option()
def cli():
    """Explain and review code changes using SYNTHETIC Git commits.

    A retelling is a named linear Git history between a real before commit (B)
    and after commit (H). Each synthetic commit is an explanatory step: its
    message is the annotation and its diff is the code shown to the reviewer.
    The first tree is EXACTLY B and the last must be EXACTLY H. Intermediate
    code need not follow the original development history or pass every check.

    Start creates a separate worktree at B. Author and revise steps there using
    ordinary Git. Validate checks endpoints, ancestry, and each diff's line
    budget. Show prints steps; view browses them interactively; check optionally
    runs project commands. This tool does not generate explanations or call an LLM.

    \b
    Example workflow (B and H are existing commits):
      git-retell start demo --base B --target H --worktree /tmp/demo
      # Edit files in /tmp/demo, then git add and git commit with explanations.
      git-retell validate demo --json
      git-retell view demo --context 6
      git-retell list

    Use COMMAND --help for options, examples, and exit behavior. Defaults are
    60 diff lines per step and 3 context lines per hunk. Start saves these;
    validate/show/view accept one-off overrides without changing stored settings.
    """


@cli.command()
@click.argument("name")
@click.option(
    "--base", required=True, help="Real before commit/revision, pinned at creation."
)
@click.option(
    "--target", required=True, help="Real after commit/revision, pinned at creation."
)
@click.option(
    "--worktree",
    required=True,
    type=click.Path(path_type=Path),
    help="New authoring directory.",
)
@click.option(
    "--budget",
    default=60,
    show_default=True,
    type=click.IntRange(min=1),
    help="Maximum diff lines per step.",
)
@click.option(
    "--context",
    default=3,
    show_default=True,
    type=click.IntRange(min=0),
    help="Save this many context lines per diff hunk for the retelling.",
)
def start(name: str, base: str, target: str, worktree: Path, budget: int, context: int):
    """Pin endpoints and create branch retell/NAME at B in a separate worktree.

    Revisions must be commits; uncommitted files are not included. Use ordinary
    Git to edit, commit, amend, or rebase the synthetic branch. The base commit
    is the anchor and is not counted as a slide. Keep one parent per step.
    The original checkout remains untouched. Existing names or branches are
    rejected; names start with a-z and contain only lowercase letters, digits,
    and hyphens. Both revisions are pinned even if their branches later move.

    \b
    Examples:
      git-retell start demo --base main --target feature --worktree /tmp/demo
      git-retell start compact --base HEAD~1 --target HEAD --worktree /tmp/compact --budget 40 --context 0

    In the new worktree, edit files and commit explanatory steps until the tree
    matches the target. Use Git amend/rebase to revise steps and validate to
    inspect progress. No commits are synthesized automatically.
    """
    retelling = start_retelling(
        root(), name, base, target, worktree.resolve(), budget, context
    )
    click.echo(
        f"SYNTHETIC retelling: retell/{name}\nAuthor in: {worktree.resolve()}\n"
        f"Base: {retelling.base}\nTarget: {retelling.target}\nBudget: {budget} diff lines · context {context}\n"
        f"Next: create explanatory commits, then git-retell validate {name}"
    )


def report_output(report: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    expansion = report["expansion_factor"]
    factor = (
        f"{expansion:.2f}×"
        if expansion is not None
        else "undefined (zero baseline or binary edits)"
    )
    click.echo(
        f"SYNTHETIC {report['name']}: {'VALID' if report['valid'] else 'INVALID / UNFINISHED'}\n"
        f"{report['step_count']} steps · budget {report['budget']} · context {report['context']} · expansion {factor}\n"
        f"Churn: real {report['real_churn']}, synthetic {report['synthetic_churn']}\n"
        f"Presentation: {report['total_presentation_lines']} total diff lines"
    )
    for step in report["steps"]:
        click.echo(
            f"{step['step']:>3} {step['commit'][:8]} {step['presentation_lines']:>4} lines  {step['subject']}"
        )
    for issue in report["issues"]:
        click.echo(f"! {issue}")


@cli.command()
@click.argument("name")
@click.option(
    "--budget",
    type=click.IntRange(min=1),
    help="Override the saved budget for this validation.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Machine-readable metrics and all violations.",
)
@click.option(
    "--context",
    type=click.IntRange(min=0),
    help="Override saved diff context for this validation.",
)
def validate(name: str, budget: int | None, as_json: bool, context: int | None):
    """Validate linear ancestry, exact endpoint trees, and every rendered diff.

    Exit 1 means unfinished/invalid. Churn is additions + deletions with rename
    detection disabled. Expansion is cumulative churn / real churn; undefined
    for a zero denominator or binary edits. Binary patches count toward budget.
    Only committed state is reviewed; worktree edits are not part of the retelling.
    Presentation size counts every header, changed line, and context line. More
    context can exceed the budget without changing the underlying code or churn.
    Neither override changes the saved defaults. Exit 0 means all rules pass.

    \b
    Examples:
      git-retell validate demo
      git-retell validate demo --budget 80 --context 6 --json
    """
    report = inspect(Retelling.load(root(), name), budget, context=context)
    report_output(report, as_json)
    if not report["valid"]:
        raise click.exceptions.Exit(1)


@cli.command()
@click.argument("name")
@click.option("--step", default=1, show_default=True, type=click.IntRange(min=1))
@click.option(
    "--all",
    "all_steps",
    is_flag=True,
    help="Print every slide, suitable for a pager or export.",
)
@click.option(
    "--context",
    type=click.IntRange(min=0),
    help="Override saved diff context for printed steps.",
)
def show(name: str, step: int, all_steps: bool, context: int | None):
    """Print explanations and full diffs to stdout for reading or export.

    Steps are numbered from 1; by default only the first is printed. --all
    prints the complete sequence. Uses saved context unless overridden, and
    does not require a terminal or enforce the budget. Run validate separately.

    \b
    Examples:
      git-retell show demo --step 2 --context 10
      git-retell show demo --all > retelling.txt
      git-retell show demo --all | less
    """
    retelling = Retelling.load(root(), name)
    commits = retelling.commits()
    if not commits or (not all_steps and step > len(commits)):
        raise click.ClickException(f"Choose a step between 1 and {len(commits)}.")
    for index in range(len(commits)) if all_steps else [step - 1]:
        click.echo(slide(retelling, commits, index, context=context))


@cli.command()
@click.argument("name")
@click.option(
    "--context",
    type=click.IntRange(min=0),
    help="Initial context; defaults to the retelling's saved setting.",
)
def view(name: str, context: int | None):
    """Browse synthetic steps with paging and adjustable diff context.

    n/p or right/left: next/previous step. j/k or down/up: scroll one line.
    f/b or PageDown/PageUp: page. Space pages, then advances at the bottom.
    g/G: top/bottom. +/-: add/remove 3 context lines; 0: reset to initial context.
    Context persists across steps. q: quit. r: redraw after resizing.

    Long lines wrap and oversized slides page in any terminal. Messages and
    every diff line remain accessible. The status reflects validation at the
    displayed context, so expanding context can change VALID to INVALID if it
    exceeds the saved budget. Live changes never alter the saved defaults.

    \b
    Examples:
      git-retell view demo
      git-retell view demo --context 12

    A terminal is required. For a pipe, file, or pager, use show instead.
    """
    view_retelling(Retelling.load(root(), name), context=context)


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("name")
@click.option(
    "--timeout", default=300.0, show_default=True, type=click.FloatRange(min=0.01)
)
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
def check(name: str, timeout: float, command: tuple[str, ...]):
    """Run COMMAND on each synthetic step in fresh detached worktrees.

    \b
    Examples:
      git-retell check demo --timeout 60 -- pytest
      git-retell check demo -- npm test

    Use -- to separate this tool's options from the check command's arguments.
    Each step starts in its own checkout, so install dependencies as needed.

    Runs project code with your permissions; worktrees are isolation for files,
    not a security sandbox. Captures output as JSON. Exit 1 means a check failed;
    failures do not affect validate. Each worktree is removed after its check.
    """
    results = checks.check(Retelling.load(root(), name), command, timeout)
    click.echo(json.dumps(results, indent=2))
    if any(not item["passed"] for item in results):
        raise click.exceptions.Exit(1)


@cli.command(name="list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print names, refs, settings, and worktrees as JSON.",
)
def list_retellings(as_json: bool):
    """List retellings stored in this repository, including unfinished ones.

    Shows pinned endpoints, branch tip, step count, saved budget/context, and
    authoring worktrees. This is an inventory, not a full budget validation.
    Broken or incomplete entries are reported so they can be inspected/deleted.

    \b
    Examples:
      git-retell list
      git-retell list --json
    """
    repo = root()
    entries = []
    for name in names(repo):
        entry = {
            "name": name,
            "worktrees": [t["worktree"] for t in worktrees(repo, name)],
        }
        try:
            retelling = Retelling.load(repo, name)
            entry.update(
                base=retelling.base,
                target=retelling.target,
                tip=retelling.tip,
                budget=retelling.budget,
                context=retelling.context,
                step_count=len(retelling.commits()),
            )
        except (click.ClickException, ValueError) as error:
            entry["error"] = str(error)
        entries.append(entry)
    if as_json:
        click.echo(json.dumps(entries, indent=2))
    elif not entries:
        click.echo("No retellings yet. Use git-retell start --help to create one.")
    else:
        for entry in entries:
            if "error" in entry:
                click.echo(f"{entry['name']}: incomplete — {entry['error']}")
                continue
            click.echo(
                f"{entry['name']}: {entry['step_count']} steps · budget {entry['budget']} · context {entry['context']}\n"
                f"  {entry['base'][:8]} → {entry['target'][:8]} · tip {entry['tip'][:8]}"
            )
            for path in entry["worktrees"]:
                click.echo(f"  worktree: {path}")


@cli.command()
@click.argument("name")
@click.option(
    "--remove-worktree",
    is_flag=True,
    help="Also remove the attached authoring worktree, only if clean and unlocked.",
)
def delete(name: str, remove_worktree: bool):
    """Delete a retelling's synthetic branch, endpoint refs, and saved settings.

    Real development branches are untouched. This removes the retelling's
    references, not a backup: export a Git bundle first if you want to keep it.
    By default, checked-out retellings are refused; detach or remove their
    worktrees yourself, or use --remove-worktree from another checkout.
    Dirty, locked, and current worktrees are never removed. Untracked and
    ignored files also block automatic removal. There is no force option.

    \b
    Examples:
      git-retell delete old-demo
      git-retell delete demo --remove-worktree
    """
    delete_retelling(root(), name, remove_worktree)
    click.echo(f"Deleted retelling {name!r}.")

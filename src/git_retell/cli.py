"""One CLI for agents authoring histories and humans reviewing them."""

import json
from pathlib import Path

import click

from . import checks
from .git import root
from .history import History, inspect
from .history import start as start_history
from .viewer import slide
from .viewer import view as view_history


@click.group()
@click.version_option()
def cli():
    """Retell a code change as SYNTHETIC explanatory Git commits.

    Agent workflow: commit the real target, then start NAME --base B --target H
    --worktree PATH. In PATH, build explanatory steps with ordinary git add and
    git commit. Naive implementations and repeated edits are welcome. Commit
    messages explain each step. Use validate NAME --json while iterating; finish
    at EXACTLY H's tree. Use view NAME for a human slideshow.

    Every step's complete Git -U3 diff (headers and context included) must fit
    the line budget. Nothing is hidden. Tests and expansion are quality signals,
    not endpoint invariants. This tool constrains and presents history; an agent
    or human chooses and authors the explanation. It does not call an LLM.
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
def start(name: str, base: str, target: str, worktree: Path, budget: int):
    """Pin endpoints and create branch retell/NAME at B in a separate worktree.

    Revisions must be commits; uncommitted files are not included. Use ordinary
    Git to edit, commit, amend, or rebase the synthetic branch. The base commit
    is the anchor and is not counted as a slide. Keep one parent per step.
    """
    history = start_history(root(), name, base, target, worktree.resolve(), budget)
    click.echo(
        f"SYNTHETIC history: retell/{name}\nAuthor in: {worktree.resolve()}\n"
        f"Base: {history.base}\nTarget: {history.target}\nBudget: {budget} diff lines\n"
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
        f"{report['step_count']} steps · budget {report['budget']} · expansion {factor}\n"
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
def validate(name: str, budget: int | None, as_json: bool):
    """Validate linear ancestry, exact endpoint trees, and every rendered diff.

    Exit 1 means unfinished/invalid. Churn is additions + deletions with rename
    detection disabled. Expansion is cumulative churn / real churn; undefined
    for a zero denominator or binary edits. Binary patches count toward budget.
    Only committed state is reviewed; worktree edits are not part of the history.
    """
    report = inspect(History.load(root(), name), budget)
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
def show(name: str, step: int, all_steps: bool):
    """Print a step's explanation and complete unified diff without a TUI."""
    history = History.load(root(), name)
    commits = history.commits()
    if not commits or (not all_steps and step > len(commits)):
        raise click.ClickException(f"Choose a step between 1 and {len(commits)}.")
    for index in range(len(commits)) if all_steps else [step - 1]:
        click.echo(slide(history, commits, index))


@cli.command()
@click.argument("name")
def view(name: str):
    """Browse synthetic steps with paging and adjustable diff context.

    n/p or right/left: next/previous step. j/k or down/up: scroll one line.
    f/b or PageDown/PageUp: page. Space pages, then advances at the bottom.
    g/G: top/bottom. +/-: add/remove 3 context lines; 0: reset to 3.
    Context persists across steps. q: quit. r: redraw after resizing.

    Long lines wrap and oversized slides page in any terminal. Messages and
    every diff line remain accessible. Context changes only the view; validation
    and saved budgets always use -U3. Run validate before using a history for review.
    """
    view_history(History.load(root(), name))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("name")
@click.option(
    "--timeout", default=300.0, show_default=True, type=click.FloatRange(min=0.01)
)
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
def check(name: str, timeout: float, command: tuple[str, ...]):
    """Run COMMAND on each synthetic step in fresh detached worktrees.

    Example: git-retell check demo --timeout 60 -- uv run pytest

    Runs project code with your permissions; worktrees are isolation for files,
    not a security sandbox. Captures output as JSON. Exit 1 means a check failed;
    failures do not affect validate. Each worktree is removed after its check.
    """
    results = checks.check(History.load(root(), name), command, timeout)
    click.echo(json.dumps(results, indent=2))
    if any(not item["passed"] for item in results):
        raise click.exceptions.Exit(1)

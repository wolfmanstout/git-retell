"""One CLI for agents authoring histories and humans reviewing them."""

import json
from pathlib import Path

import click

from . import checks
from .git import pathspecs, root
from .retelling import Retelling, inspect, names, save_settings, worktrees
from .retelling import delete as delete_retelling
from .retelling import finish as finish_retelling
from .retelling import resume as resume_retelling
from .retelling import start as start_retelling
from .viewer import selected_steps, slide
from .viewer import view as view_retelling
from .web import web as web_retelling


@click.group()
@click.version_option()
def cli():
    """Explain and review code changes using SYNTHETIC Git commits.

    A retelling is a named linear Git history between a real before commit (B)
    and after commit (H). Each synthetic commit is an explanatory step: its
    message is the annotation and its diff is the code shown to the reviewer.
    The first tree is EXACTLY B and the last must be EXACTLY H. Intermediate
    code need not follow the original development history or pass every check.

    A partial retelling (start --partial) may leave some changed files out: each
    file either reaches its exact target version or stays exactly as in B. Omit
    --base to build from an empty tree instead of B.

    Start creates a separate worktree at B. Author and revise steps there using
    ordinary Git. Validate checks endpoints, ancestry, and each diff's line
    budget. Finish validates and removes the authoring worktree; resume checks
    the retelling out again for revision. Show prints steps; view browses them
    interactively; web opens an animated browser slideshow; check optionally
    runs project commands. This tool does not generate explanations or call an
    LLM.

    \b
    Example workflow (B and H are existing commits):
      git-retell start demo --base B --target H --worktree /tmp/demo
      # Edit files in /tmp/demo, then git add and git commit with explanations.
      git-retell validate demo --json
      git-retell finish demo
      git-retell view demo --context 6
      git-retell web demo
      git-retell list

    Use COMMAND --help for options, examples, and exit behavior. Defaults are
    60 diff lines per step and 3 context lines per hunk. Start saves these;
    validate/show/view accept one-off overrides without changing stored settings.
    """


@cli.command()
@click.argument("name")
@click.option(
    "--base",
    help="Real before commit/revision, pinned at creation. "
    "Omit to build the files from scratch, starting with an empty tree.",
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
@click.option(
    "--partial",
    is_flag=True,
    help="Allow leaving some changed files out of the retelling.",
)
def start(
    name: str,
    base: str | None,
    target: str,
    worktree: Path,
    budget: int,
    context: int,
    partial: bool,
):
    """Pin endpoints and create branch retell/NAME at B in a separate worktree.

    Revisions must be commits; uncommitted files are not included. Use ordinary
    Git to edit, commit, amend, or rebase the synthetic branch. The base commit
    is the anchor and is not counted as a slide. Keep one parent per step.
    The original checkout remains untouched. Existing names or branches are
    rejected; names start with a-z and contain only lowercase letters, digits,
    and hyphens. Both revisions are pinned even if their branches later move.

    Without --base, B is a new parentless commit of the empty tree, so the
    retelling builds every file from nothing. This pairs well with --partial.

    With --partial, the retelling may leave out some of the files that differ
    between B and H, such as lock files, generated code, or tests. It is all or
    nothing per file: every file the history changes must end at exactly its
    target version, and every other file must remain exactly as in B. Choose
    which files to leave out; viewers list them as not retold.

    \b
    Examples:
      git-retell start demo --base main --target feature --worktree /tmp/demo
      git-retell start compact --base HEAD~1 --target HEAD --worktree /tmp/compact --budget 40 --context 0
      git-retell start core --base main --target feature --worktree /tmp/core --partial
      git-retell start fresh --target HEAD --worktree /tmp/fresh --partial

    In the new worktree, edit files and commit explanatory steps until the tree
    matches the target. Use Git amend/rebase to revise steps and validate to
    inspect progress. No commits are synthesized automatically.
    """
    retelling = start_retelling(
        root(), name, base, target, worktree.resolve(), budget, context, partial
    )
    scratch = " (empty tree; building from scratch)" if base is None else ""
    click.echo(
        f"SYNTHETIC retelling: retell/{name}\nAuthor in: {worktree.resolve()}\n"
        f"Base: {retelling.base}{scratch}\nTarget: {retelling.target}\n"
        f"Budget: {budget} diff lines · context {context}{' · partial' if partial else ''}\n"
        f"Next: create explanatory commits, then git-retell finish {name}"
    )


def file_filters(command):
    """Add --path and --exclude, which narrow what a viewer shows, not validation."""
    command = click.option(
        "--exclude",
        "exclude",
        multiple=True,
        metavar="PATHSPEC",
        help="Hide files matching this Git pathspec. Repeatable.",
    )(command)
    return click.option(
        "--path",
        "include",
        multiple=True,
        metavar="PATHSPEC",
        help="Show only files matching this Git pathspec. Repeatable.",
    )(command)


@cli.command()
@click.argument("name")
@click.option(
    "--worktree",
    required=True,
    type=click.Path(path_type=Path),
    help="New authoring directory.",
)
def resume(name: str, worktree: Path):
    """Check out branch retell/NAME in a new worktree to revise a retelling.

    Use after finish (or after removing the worktree) to amend, rebase, or add
    steps. Refused if the retelling is already checked out elsewhere.

    \b
    Examples:
      git-retell resume demo --worktree /tmp/demo
    """
    retelling = resume_retelling(root(), name, worktree.resolve())
    click.echo(
        f"SYNTHETIC retelling: retell/{name}\nAuthor in: {worktree.resolve()}\n"
        f"Steps: {len(retelling.commits())}\n"
        f"Next: revise with ordinary Git, then git-retell finish {name}"
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
    kind = " (partial)" if report["partial"] else ""
    if report["from_scratch"]:
        kind += " (from scratch)"
    click.echo(
        f"SYNTHETIC {report['name']}{kind}: {'VALID' if report['valid'] else 'INVALID / UNFINISHED'}\n"
        f"{report['step_count']} steps · budget {report['budget']} · context {report['context']} · expansion {factor}\n"
        f"Churn: real {report['real_churn']}, synthetic {report['synthetic_churn']}\n"
        f"Presentation: {report['total_presentation_lines']} total diff lines"
    )
    for step in report["steps"]:
        click.echo(
            f"{step['step']:>3} {step['commit'][:8]} {step['presentation_lines']:>4} lines  {step['subject']}"
        )
    if omitted := report["omitted_files"]:
        click.echo(f"Not retold ({len(omitted)} files left as in the base):")
        for item in omitted:
            counts = (
                "binary"
                if item["binary_files"]
                else f"+{item['added']} -{item['deleted']}"
            )
            click.echo(f"    {item['path']}  {counts}")
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

    Exit 1 means unfinished/invalid. A partial retelling also lists the files
    it leaves out; real churn and expansion then cover only retold files. Churn is additions + deletions with rename
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


def report_removed(paths: list[str]) -> None:
    for path in paths:
        click.echo(f"Removed worktree: {path}")
        if Path(path).exists():
            click.echo(f"  Left non-Git leftovers on disk: {path}")


@cli.command()
@click.argument("name")
def finish(name: str):
    """Validate a retelling, then remove its authoring worktree.

    Uses the saved budget and context. If validation fails, the report is
    printed, the worktree is kept, and the exit code is 1. The synthetic branch
    is always kept; use resume to revise it later. Current, locked, and dirty
    worktrees (uncommitted or untracked files) are refused; ignored files such
    as build output are removed with the worktree. If the worktree directory
    was already deleted, only this retelling's stale Git entry is cleared.

    \b
    Examples:
      git-retell finish demo
    """
    report, removed = finish_retelling(root(), name)
    report_output(report, False)
    if not report["valid"]:
        raise click.exceptions.Exit(1)
    report_removed(removed)
    click.echo(f"View: git-retell view {name}  ·  git-retell web {name}")


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
@file_filters
def show(
    name: str,
    step: int,
    all_steps: bool,
    context: int | None,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
):
    """Print explanations and full diffs to stdout for reading or export.

    Steps are numbered from 1; by default only the first is printed. --all
    prints the complete sequence. Uses saved context unless overridden, and
    does not require a terminal or enforce the budget. Run validate separately.

    --path and --exclude take Git pathspecs (directories, globs such as
    '*.lock') and limit each diff to the matching files. With --all, steps that
    change none of them are skipped; step numbers stay those of the full history.

    \b
    Examples:
      git-retell show demo --step 2 --context 10
      git-retell show demo --all > retelling.txt
      git-retell show demo --all | less
      git-retell show demo --all --exclude tests/ --exclude '*.lock'
    """
    retelling = Retelling.load(root(), name)
    commits = retelling.commits()
    if not commits or (not all_steps and step > len(commits)):
        raise click.ClickException(f"Choose a step between 1 and {len(commits)}.")
    specs = pathspecs(include, exclude)
    indices = selected_steps(retelling, specs) if all_steps else [step - 1]
    for index in indices:
        click.echo(slide(retelling, commits, index, context=context, pathspecs=specs))


@cli.command()
@click.argument("name")
@click.option(
    "--context",
    type=click.IntRange(min=0),
    help="Initial context; defaults to the retelling's saved setting.",
)
@file_filters
def view(
    name: str, context: int | None, include: tuple[str, ...], exclude: tuple[str, ...]
):
    """Browse synthetic steps with paging and adjustable diff context.

    n/p or right/left: next/previous step. j/k or down/up: scroll one line.
    f/b or PageDown/PageUp: page. Space pages, then advances at the bottom.
    g/G: top/bottom. +/-: add/remove 3 context lines; 0: reset to initial context.
    Context persists across steps. q: quit. r: redraw after resizing.

    Long lines wrap and oversized slides page in any terminal. Messages and
    every diff line remain accessible. The status reflects validation at the
    displayed context, so expanding context can change VALID to INVALID if it
    exceeds the saved budget. Live changes never alter the saved defaults.

    --path and --exclude take Git pathspecs and limit each diff to the matching
    files; n/p skip steps that change none of them. Validation still covers
    every file.

    \b
    Examples:
      git-retell view demo
      git-retell view demo --context 12
      git-retell view demo --path src/parser.py

    A terminal is required. For a pipe, file, or pager, use show instead.
    """
    view_retelling(
        Retelling.load(root(), name),
        context=context,
        pathspecs=pathspecs(include, exclude),
    )


@cli.command()
@click.argument("name")
@click.option(
    "--context",
    type=click.IntRange(min=0),
    help="Initial context; defaults to the retelling's saved setting.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the page here instead of a temporary file.",
)
@click.option(
    "--open/--no-open",
    "open_browser",
    default=True,
    show_default=True,
    help="Open the page in the default browser.",
)
@file_filters
def web(
    name: str,
    context: int | None,
    output: Path | None,
    open_browser: bool,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
):
    """Write a self-contained HTML slideshow and open it in a browser.

    Transitions animate how each step connects to its neighbors: lines that
    leave collapse, surviving lines move and recolor, new lines expand, and
    files slide in or out. A seek bar charts each step's churn and marks where
    each file first appears. Each file header links to that file's previous
    and next change and labels its final edit. Code is syntax highlighted.

    \b
    Keys: right/left or n/p: next/previous step. j/k: scroll.
    +/-: add/remove 3 context lines; 0: reset; f: toggle whole files.
    /: choose which files to show. Home/End: first/last step. ?: help.

    The Files panel (/) and each file's focus button hide files; navigation
    then skips steps that change none of the shown files. --path and --exclude
    take Git pathspecs and choose the files shown at first. The page still
    embeds every file, so viewers can show the rest.

    The page embeds every file version it shows, needs no server or network,
    and can be shared as a single file. It is a snapshot; rerun after editing.

    \b
    Examples:
      git-retell web demo
      git-retell web demo --no-open -o demo.html
      git-retell web demo --exclude tests/ --exclude '*.lock'
    """
    path = web_retelling(
        Retelling.load(root(), name),
        output,
        open_browser,
        context,
        pathspecs(include, exclude),
    )
    click.echo(f"Wrote {path}")


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


@cli.command()
@click.argument("name")
@click.option(
    "--budget", type=click.IntRange(min=1), help="Save a new diff line budget."
)
@click.option(
    "--context", type=click.IntRange(min=0), help="Save new context lines per hunk."
)
@click.option(
    "--partial/--no-partial",
    default=None,
    help="Allow or forbid leaving changed files out of the retelling.",
)
def configure(name: str, budget: int | None, context: int | None, partial: bool | None):
    """Print or change a retelling's saved budget, context, and partial setting.

    Settings are stored as a JSON blob at refs/retell/NAME/settings, so they
    travel with the retelling's other refs. With no options, prints them.

    \b
    Examples:
      git-retell configure demo
      git-retell configure demo --budget 80 --context 6
      git-retell configure demo --partial
    """
    repo = root()
    Retelling.load(repo, name)
    changes = {"budget": budget, "context": context, "partial": partial}
    saved = save_settings(
        repo,
        name,
        **{key: value for key, value in changes.items() if value is not None},
    )
    click.echo(
        f"{name}: budget {saved['budget']} · context {saved['context']}"
        f" · {'partial' if saved['partial'] else 'complete'}"
    )


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
                partial=retelling.partial,
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
                f"{entry['name']}: {entry['step_count']} steps · budget {entry['budget']} · context {entry['context']}"
                f"{' · partial' if entry['partial'] else ''}\n"
                f"  {entry['base'][:8]} → {entry['target'][:8]} · tip {entry['tip'][:8]}"
            )
            for path in entry["worktrees"]:
                click.echo(f"  worktree: {path}")


@cli.command()
@click.argument("name")
def delete(name: str):
    """Delete a retelling's synthetic branch, refs, settings, and worktree.

    Real development branches are untouched. This removes the retelling's
    references, not a backup: export a Git bundle first if you want to keep it.
    The authoring worktree is removed too. Nothing is deleted if that worktree
    is current, locked, or has uncommitted changes or untracked files; ignored
    files are removed with it. Worktrees switched away from retell/NAME are
    left alone. There is no force option.

    \b
    Examples:
      git-retell delete old-demo
    """
    report_removed(delete_retelling(root(), name))
    click.echo(f"Deleted retelling {name!r}.")

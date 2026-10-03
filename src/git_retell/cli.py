"""One CLI for agents authoring histories and humans reviewing them."""

import json
from pathlib import Path

import click

from . import checks
from .git import git, pathspecs, root
from .history import History
from .retelling import (
    Retelling,
    inspect,
    names,
    retarget,
    save_settings,
    snapshot,
    worktrees,
)
from .retelling import delete as delete_retelling
from .retelling import finish as finish_retelling
from .retelling import resume as resume_retelling
from .retelling import start as start_retelling
from .viewer import Story, selected_steps, slide
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
    file either reaches its exact target version or stays exactly as in B. Use
    --from-scratch to build from an empty tree instead of B. To retell work you
    have not committed, use --to-uncommitted or --to-staged.

    Start creates a separate worktree at B. Author and revise steps there using
    ordinary Git. Validate checks endpoints, ancestry, and each diff's line
    budget. Finish validates and removes the authoring worktree; resume checks
    the retelling out again for revision. Show prints steps; view browses them
    interactively; web opens an animated browser slideshow; test optionally
    runs project commands on every step. These four also take --from REV
    instead of NAME to step through real commits, such as a branch since main.
    This tool does not generate explanations or call an LLM.

    \b
    Example workflow (B and H are existing commits):
      git-retell start demo --from B --to H --worktree /tmp/demo
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


def target_options(command):
    """Add --to, --to-uncommitted, and --to-staged; choose one with chosen_target."""
    command = click.option(
        "--to-staged",
        is_flag=True,
        help="Snapshot the staged changes (the index) on top of HEAD as the target.",
    )(command)
    command = click.option(
        "--to-uncommitted",
        is_flag=True,
        help="Snapshot every uncommitted change, including untracked files that "
        "are not ignored, on top of HEAD as the target.",
    )(command)
    return click.option(
        "--to",
        "target",
        metavar="REV",
        help="Real after commit/revision (the target). Defaults to HEAD, "
        "except in configure.",
    )(command)


def chosen_target(
    repo: Path,
    target: str | None,
    uncommitted: bool,
    staged: bool,
    default: str | None = "HEAD",
) -> tuple[str, str]:
    """Resolve the --to* option given, or DEFAULT, to a revision and a description.

    Snapshots are new commits; the description lists the untracked files that
    an uncommitted snapshot captured, so a stray file is easy to spot. When
    the default applies, warn if uncommitted work is being left out.
    """
    if target is None and not uncommitted and not staged and default is not None:
        if git(repo, "status", "--porcelain").strip():
            click.echo(
                "Note: uncommitted changes are not included; "
                "add --to-uncommitted to include them.",
                err=True,
            )
        return default, ""
    if sum([target is not None, uncommitted, staged]) != 1:
        raise click.UsageError(
            "Pass exactly one of --to REV, --to-uncommitted, or --to-staged."
        )
    if target is not None:
        return target, ""
    commit, untracked = snapshot(repo, staged)
    note = f" (snapshot of {'staged' if staged else 'uncommitted'} changes on HEAD)"
    if untracked:
        note += f"\nIncludes {len(untracked)} untracked files:" + "".join(
            f"\n  {path}" for path in untracked
        )
    return commit, note


def range_options(command):
    """Add --from/--from-scratch and the --to options for viewing real commits."""
    command = target_options(command)
    command = click.option(
        "--from-scratch",
        is_flag=True,
        help="With no NAME: show every commit back to the first one.",
    )(command)
    return click.option(
        "--from",
        "base",
        metavar="REV",
        help="With no NAME: show the commits after REV, up to --to (default HEAD).",
    )(command)


def load_story(
    name: str | None,
    base: str | None,
    from_scratch: bool,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
) -> Story:
    """A retelling by NAME, or the real commits that --from and --to select."""
    ranged = from_scratch or to_uncommitted or to_staged
    if name is not None:
        if ranged or base is not None or target is not None:
            raise click.UsageError("Pass a retelling NAME or --from/--to, not both.")
        return Retelling.load(root(), name)
    if (base is None) == (not from_scratch):
        raise click.UsageError(
            "Pass a retelling NAME, or --from REV or --from-scratch to show real commits."
        )
    repo = root()
    end = target or (
        "uncommitted" if to_uncommitted else "staged" if to_staged else "HEAD"
    )
    target, _ = chosen_target(repo, target, to_uncommitted, to_staged)
    return History.load(repo, base, target, f"{base}..{end}" if base else end)


@cli.command()
@click.argument("name")
@click.option(
    "--from",
    "base",
    metavar="REV",
    help="Real before commit/revision (the base), pinned at creation.",
)
@click.option(
    "--from-scratch",
    is_flag=True,
    help="Start from a new empty-tree commit instead of a real base.",
)
@target_options
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
    from_scratch: bool,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
    worktree: Path,
    budget: int,
    context: int,
    partial: bool,
):
    """Pin endpoints and create branch retell/NAME at B in a separate worktree.

    Revisions must be commits; --to defaults to HEAD, with a note if that
    leaves uncommitted changes out. For work you have not committed, the
    target can instead be a snapshot:

    \b
      --to-uncommitted  staged, unstaged, and untracked (not ignored) files
      --to-staged       only the staged changes in the index

    Either one commits a SYNTHETIC snapshot on top of HEAD without touching
    your checkout or index, pins it as the target, and makes --from default to
    HEAD. The snapshot is frozen; after more edits, configure NAME
    --to-uncommitted takes a new one.

    Use ordinary Git to edit, commit, amend, or rebase the synthetic branch.
    The base commit is the anchor and is not counted as a slide. Keep one parent per step.
    The original checkout remains untouched. Existing names or branches are
    rejected; names start with a-z and contain only lowercase letters, digits,
    and hyphens. Both revisions are pinned even if their branches later move.

    Pass --from B, or --from-scratch to make B a new parentless commit of the
    empty tree, so the retelling builds every file from nothing. This pairs
    well with --partial.

    With --partial, the retelling may leave out some of the files that differ
    between B and H, such as lock files, generated code, or tests. It is all or
    nothing per file: every file the history changes must end at exactly its
    target version, and every other file must remain exactly as in B. Choose
    which files to leave out; viewers list them as not retold.

    \b
    Examples:
      git-retell start demo --from main --to feature --worktree /tmp/demo
      git-retell start branch --from main --worktree /tmp/branch
      git-retell start compact --from HEAD~1 --to HEAD --worktree /tmp/compact --budget 40 --context 0
      git-retell start core --from main --to feature --worktree /tmp/core --partial
      git-retell start fresh --from-scratch --to HEAD --worktree /tmp/fresh --partial
      git-retell start wip --to-uncommitted --worktree /tmp/wip

    In the new worktree, edit files and commit explanatory steps until the tree
    matches the target. Use Git amend/rebase to revise steps and validate to
    inspect progress. No commits are synthesized automatically.
    """
    if base is None and not from_scratch and (to_uncommitted or to_staged):
        base = "HEAD"
    if (base is None) == (not from_scratch):
        raise click.UsageError(
            "Pass either --from REV or --from-scratch (to build from an empty tree)."
        )
    repo = root()
    target, note = chosen_target(repo, target, to_uncommitted, to_staged)
    retelling = start_retelling(
        repo, name, base, target, worktree.resolve(), budget, context, partial
    )
    scratch = " (empty tree; building from scratch)" if from_scratch else ""
    click.echo(
        f"SYNTHETIC retelling: retell/{name}\nAuthor in: {worktree.resolve()}\n"
        f"Base: {retelling.base}{scratch}\nTarget: {retelling.target}{note}\n"
        f"Budget: {budget} diff lines · context {context}{' · partial' if partial else ''}\n"
        f"Next: create explanatory commits, then git-retell finish {name}"
    )


def file_filters(command):
    """Add --include and --exclude, which narrow what a viewer shows, not validation."""
    command = click.option(
        "--exclude",
        "exclude",
        multiple=True,
        metavar="PATHSPEC",
        help="Hide files matching this Git pathspec. Repeatable.",
    )(command)
    return click.option(
        "--include",
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
@click.argument("name", required=False)
@range_options
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
    name: str | None,
    base: str | None,
    from_scratch: bool,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
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

    --include and --exclude take Git pathspecs (directories, globs such as
    '*.lock') and limit each diff to the matching files. With --all, steps that
    change none of them are skipped; step numbers stay those of the full history.

    With --from REV (or --from-scratch) instead of NAME, shows real commits:
    the first-parent chain reachable from --to (default HEAD) but not from REV,
    each against the commit before it, like git log REV..HEAD. A branch thus
    starts where it forked even if REV moved on. --to-uncommitted or
    --to-staged adds a final snapshot of work in progress on top of HEAD.
    Real commits have no budget or validation.

    \b
    Examples:
      git-retell show demo --step 2 --context 10
      git-retell show demo --all > retelling.txt
      git-retell show demo --all | less
      git-retell show demo --all --exclude tests/ --exclude '*.lock'
      git-retell show --from main --all
    """
    retelling = load_story(name, base, from_scratch, target, to_uncommitted, to_staged)
    commits = retelling.commits()
    if not commits or (not all_steps and step > len(commits)):
        raise click.ClickException(f"Choose a step between 1 and {len(commits)}.")
    specs = pathspecs(include, exclude)
    indices = selected_steps(retelling, specs) if all_steps else [step - 1]
    for index in indices:
        click.echo(slide(retelling, commits, index, context=context, pathspecs=specs))


@cli.command()
@click.argument("name", required=False)
@range_options
@click.option(
    "--context",
    type=click.IntRange(min=0),
    help="Initial context; defaults to the retelling's saved setting.",
)
@file_filters
def view(
    name: str | None,
    base: str | None,
    from_scratch: bool,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
    context: int | None,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
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

    --include and --exclude take Git pathspecs and limit each diff to the matching
    files; n/p skip steps that change none of them. Validation still covers
    every file.

    With --from REV (or --from-scratch) instead of NAME, shows real commits:
    the first-parent chain reachable from --to (default HEAD) but not from REV,
    each against the commit before it, like git log REV..HEAD. A branch thus
    starts where it forked even if REV moved on. --to-uncommitted or
    --to-staged adds a final snapshot of work in progress on top of HEAD.
    Real commits have no budget or validation.

    \b
    Examples:
      git-retell view demo
      git-retell view demo --context 12
      git-retell view demo --include src/parser.py
      git-retell view --from main --to-uncommitted

    A terminal is required. For a pipe, file, or pager, use show instead.
    """
    view_retelling(
        load_story(name, base, from_scratch, target, to_uncommitted, to_staged),
        context=context,
        pathspecs=pathspecs(include, exclude),
    )


@cli.command()
@click.argument("name", required=False)
@range_options
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
    name: str | None,
    base: str | None,
    from_scratch: bool,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
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
    then skips steps that change none of the shown files. --include and --exclude
    take Git pathspecs and choose the files shown at first. The page still
    embeds every file, so viewers can show the rest.

    The page embeds every file version it shows, needs no server or network,
    and can be shared as a single file. It is a snapshot; rerun after editing.

    With --from REV (or --from-scratch) instead of NAME, shows real commits:
    the first-parent chain reachable from --to (default HEAD) but not from REV,
    each against the commit before it, like git log REV..HEAD. A branch thus
    starts where it forked even if REV moved on. --to-uncommitted or
    --to-staged adds a final snapshot of work in progress on top of HEAD.
    Real commits have no budget or validation.
    The page then shows each commit's author and date, and its line-lifetime
    marks show code that a later commit rewrote or removed.

    \b
    Examples:
      git-retell web demo
      git-retell web demo --no-open -o demo.html
      git-retell web demo --exclude tests/ --exclude '*.lock'
      git-retell web --from main
    """
    story = load_story(name, base, from_scratch, target, to_uncommitted, to_staged)
    if len(story.commits()) > LARGE_HISTORY:
        click.echo(
            f"Embedding {len(story.commits())} commits; the page may be large.",
            err=True,
        )
    path = web_retelling(
        story,
        output,
        open_browser,
        context,
        pathspecs(include, exclude),
    )
    click.echo(f"Wrote {path}")


# Pages for longer histories can grow large, since they embed every version.
LARGE_HISTORY = 200


@cli.command(name="test", context_settings={"ignore_unknown_options": True})
@click.argument("name", required=False)
@range_options
@click.option(
    "--timeout",
    default=300.0,
    show_default=True,
    type=click.FloatRange(min=0.01),
    help="Seconds allowed per step.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print exit codes, output, and timeouts for every step as JSON.",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def run_tests(
    name: str | None,
    base: str | None,
    from_scratch: bool,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
    timeout: float,
    as_json: bool,
    command: tuple[str, ...],
):
    """Run COMMAND on every step, each in a fresh detached worktree.

    \b
    Examples:
      git-retell test demo --timeout 60 -- pytest
      git-retell test demo --json -- npm test
      git-retell test --from main -- pytest

    With --from REV (or --from-scratch) instead of NAME, runs COMMAND on each
    real commit that show --from REV would list, with the same --to options.

    Use -- to separate this tool's options from the command's arguments.
    Each step starts in its own checkout, so install dependencies as needed.
    The base is not a step and is not tested.

    Runs project code with your permissions; worktrees are isolation for files,
    not a security sandbox. Prints each step's result and the output of failed
    steps, or everything with --json. Exit 1 means a step failed; failures do
    not affect validate. Each worktree is removed after its run.
    """
    if name is not None and (base is not None or from_scratch):
        # Without NAME, the first word of COMMAND fills that argument.
        name, command = None, (name, *command)
    if not command:
        raise click.UsageError("Missing COMMAND to run on every step.")
    retelling = load_story(name, base, from_scratch, target, to_uncommitted, to_staged)
    results = checks.check(retelling, command, timeout)
    if as_json:
        click.echo(json.dumps(results, indent=2))
    else:
        for item in results:
            subject = retelling.message(item["commit"]).split("\n")[0]
            status = (
                "pass"
                if item["passed"]
                else "timeout"
                if item["timed_out"]
                else f"fail ({item['returncode']})"
            )
            click.echo(f"{item['step']:>3} {item['commit'][:8]} {status:<9} {subject}")
            if not item["passed"]:
                for line in (item["stdout"] + item["stderr"]).rstrip().splitlines():
                    click.echo(f"      {line}")
        failed = sum(not item["passed"] for item in results)
        click.echo(f"{len(results) - failed} of {len(results)} steps passed.")
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
@target_options
def configure(
    name: str,
    budget: int | None,
    context: int | None,
    partial: bool | None,
    target: str | None,
    to_uncommitted: bool,
    to_staged: bool,
):
    """Print or change a retelling's saved settings, or pin a new target.

    Settings are stored as a JSON blob at refs/retell/NAME/settings, so they
    travel with the retelling's other refs. With no options, prints them.

    --to, --to-uncommitted, or --to-staged replaces the pinned target, for
    example to take a new snapshot after more edits or to follow a rebased
    real change. The history is then validated against the new target. The
    base stays pinned, since the synthetic branch is anchored there.

    \b
    Examples:
      git-retell configure demo
      git-retell configure demo --budget 80 --context 6
      git-retell configure demo --partial
      git-retell configure wip --to-uncommitted
    """
    repo = root()
    Retelling.load(repo, name)
    if target is not None or to_uncommitted or to_staged:
        target, note = chosen_target(
            repo, target, to_uncommitted, to_staged, default=None
        )
        click.echo(f"Target: {retarget(repo, name, target).target}{note}")
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

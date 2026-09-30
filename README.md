# git-retell

[![PyPI](https://img.shields.io/pypi/v/git-retell.svg)](https://pypi.org/project/git-retell/)
[![Changelog](https://img.shields.io/github/v/release/wolfmanstout/git-retell?include_prereleases&label=changelog)](https://github.com/wolfmanstout/git-retell/releases)
[![Tests](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml/badge.svg)](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/wolfmanstout/git-retell/blob/main/LICENSE)

Synthetic Git histories for code review

Explain a real code transformation **B → H** with a synthetic Git history
**B → S1 → S2 → … → H**. Each commit is a slide; its message explains its diff.
An agent or human authors the steps. This CLI supplies the authoring worktree,
validation, metrics, optional checks, and terminal and browser slideshows. No
LLM API required.

The endpoints must be exact. Intermediate implementations can be temporary,
change the same lines repeatedly, or fail tests. They are explanations, not a
claim about how the code was originally developed.

## Installation

Requires Python 3.11+ and Git with worktree support. The package is not yet
published on PyPI. For now, install from a checkout of this repository:

```sh
uv tool install .
```

You can also install from the checkout using `pip install .` in a virtual
environment or `pipx install .`.

Once published on PyPI, install using `pip` or `pipx`:

```sh
pip install git-retell
# Or install the CLI in an isolated environment:
pipx install git-retell
```

## Usage

For help, run:

```sh
git-retell --help
```

With the package installed in your Python environment, you can also use:

```sh
python -m git_retell --help
```

### Example workflow

After installation, run `git-retell` in the repository you want to explain:

```sh
git-retell --help

# Commit the real change first; B and H must resolve to commits.
git-retell start demo --base HEAD~1 --target HEAD \
  --worktree /tmp/retell-demo --budget 40

# In /tmp/retell-demo, use ordinary Git to author the explanation:
# edit files, git add ..., git commit -m 'Explain why this step exists'
# Repeat, amend, or rebase as needed. Finish at exactly H's tree.

# Review the retelling using the installed CLI:
git-retell validate demo --json
git-retell finish demo   # validate, then remove /tmp/retell-demo
git-retell show demo --step 1
git-retell view demo
git-retell web demo
git-retell check demo --timeout 60 -- pytest
git-retell resume demo --worktree /tmp/retell-demo   # revise it later
git-retell list
```

Installing the CLI makes `git-retell` available while working in any repository.
All commands explain their options with `--help`.

## What is validated?

- The branch is anchored at the exact pinned base commit, hence its exact tree.
- Every subsequent commit has exactly one parent: the preceding step.
- The final tree ID equals the pinned target tree ID. File contents, names,
  modes, symlinks, and submodule pointers all participate in tree identity.
- Each complete rendered diff has at most the configured number of lines.

`validate` exits 0 only when all four hold; it exits 1 for an unfinished or invalid
history. No test result or expansion threshold changes that verdict. Only
committed states participate. Untracked files and working-tree edits are excluded.
An empty history is valid only if the pinned endpoints already have equal trees.

The renderer uses ordinary Git unified diffs with configurable context (three
lines by default), headers,
containing-function text, and no rename detection. Binary changes use full Git
binary patches. External diff tools and text conversions are disabled so no
edits are replaced by a summary. The same renderer serves validation and viewing.
Diff lines are counted by newline, including headers, context, blank lines, and
"no newline" markers. No file, hunk, import, or supporting edit is hidden.
Git attributes can still influence hunk headers and text/binary classification.

## Metrics and the review frame

Churn means additions + deletions, using Git numstat without rename detection.
Expansion is cumulative synthetic churn divided by real B→H churn. It is
informational: 2× may be a better explanation than 1×. The ratio is undefined
for zero real churn or any binary edits; text churn remains available. Mode-only
changes still consume presentation lines even when their line churn is zero.
Reports include each step's hash, subject, churn and diff lines, plus totals.

The budget covers the diff at the selected context setting. Messages, navigation,
wrapping, and extra context can require more terminal space. The viewer pages
through slides of any size, including on terminals smaller than the authoring
budget. It labels invalid histories; paging does not waive budget validation.

Viewer controls:

- `n` / right arrow and `p` / left arrow: next and previous step.
- `j` / down arrow and `k` / up arrow: scroll one line.
- `f` / PageDown and `b` / PageUp: page down and up.
- Space: page down, then advance to the next step at the bottom.
- `g` / `G`: top / bottom of the current slide.
- `+` (or `=`) / `-`: add / remove three diff context lines, down to zero.
- `0`: reset to the initial context (the flag or saved setting). Context persists across steps.
- `r`: redraw after resizing; `q`: quit.

Changing context returns to the top of the slide. The footer shows the step,
context (`U3`, `U6`, etc.), and visible line range. All message and diff lines
remain accessible, including wrapped lines. Context is a viewing preference;
saved settings and code churn remain unchanged. The VALID/INVALID status is
recomputed at the displayed context, so expanding context can exceed the budget.
`show NAME --all` prints every slide for a pager or text export. Terminal controls
are visibly escaped and tabs expanded. The MVP budgets lines, not reading time.

## Web viewer

`git-retell web NAME` writes a self-contained HTML slideshow and opens it in
your browser. Use `-o FILE` to choose where it is written and `--no-open` to
skip the browser. The page needs no server or network access, so the file can
be shared as is. It is a snapshot: rerun the command after editing the history.

Transitions show how each step connects to its neighbors. Every line keeps one
identity for as long as it is unchanged, using Git's own line matching, so the
viewer can animate the difference between any two slides:

- Lines the next slide no longer shows collapse; new lines expand into place.
- Lines added in one step settle from green to plain context in the next;
  context lines the next step deletes fade to gray.
- Moving to another part of the same file collapses the old hunk, glides the
  view, and expands the new hunk. Each file header has a small ruler showing
  which part of the file is visible and where it changed.
- Files that leave the slide swipe away; files that join it slide in. New files
  are flagged with a highlighted header.
- Like Git's hunk-header function context, a hidden stretch above a hunk names
  its enclosing scopes, such as `class History › def load(...)`, with the
  header's line number. Scopes come from indentation (definitions and other
  block openers, not control flow) or from Markdown heading levels, and update
  as you change context.

A seek bar charts each step's additions and deletions. A fixed row marks every
step that introduces (◆) or deletes (◇) files, and file names label them where
space allows; hover for a step's subject and files, and click or drag to jump.
Code is syntax highlighted with Pygments.

Web viewer controls: right/left arrow, `n`/`p`, or space: next and previous step.
Home/End: first/last step. `j`/`k`: scroll. `+`/`-`: context, `0`: reset, `f`:
whole files. `t`: theme. `?`: help. The URL fragment remembers the step.
The VALID/INVALID badge reflects the context given on the command line. Like
`view`, live context changes in the page do not revalidate or change settings.

## Configuration

`start --budget N --context N` saves defaults for a retelling. The defaults are
60 presentation lines per step and 3 unchanged context lines on each side of a
hunk. Zero context is allowed. Context can change hunk grouping and presentation
size; it does not change tree identity or code churn.

```sh
git-retell start demo --base main --target feature --worktree /tmp/demo --context 6
git-retell validate demo --context 0 --budget 40 --json
git-retell show demo --step 2 --context 12
git-retell view demo --context 12
```

`validate`, `show`, and `view` use saved context unless you pass `--context`.
Overrides apply only to that invocation. The validation report includes the
context used for every presentation-size metric. Checks run code and do not need
a diff context setting. Existing retellings without saved context use 3 lines.
To update saved defaults later, use `git config retell.demo.context 6` or
`git config retell.demo.budget 80`.

## Finishing, resuming, listing, and deleting retellings

```sh
git-retell finish demo
git-retell resume demo --worktree /tmp/demo
git-retell list
git-retell list --json
git-retell delete demo
git-retell delete demo --remove-worktree
```

The authoring worktree is only needed while writing steps; every other command
reads the retelling's refs. `finish` validates with the saved settings and, only
if the retelling is valid, removes its authoring worktree while keeping the
synthetic branch. An invalid retelling keeps its worktree and exits 1. `resume`
checks the branch out in a new worktree so you can amend, rebase, or add steps,
then `finish` again.

`list` shows names, pinned endpoints, tips, step counts, saved settings, and
attached worktrees. It includes unfinished and incomplete entries; use `validate`
for the full correctness and budget report.

`delete` removes the named synthetic branch, endpoint refs, and saved config,
leaving real development branches intact. By default it refuses a checked-out
retelling. Detach/remove its worktree yourself, or use `--remove-worktree` from
another checkout to remove a clean, unlocked worktree too. `finish` and `delete`
refuse current or locked worktrees and those with uncommitted changes or
untracked files. Ignored files, such as build output, are removed with the
worktree. Export a Git bundle first if you want to keep the retelling; deletion
is not archival.

## Suggested agent prompt

The CLI does not prescribe an explanatory style. Here is an editable starting
point that favors progressive refinement; change the style, budget, checks, and
scope to suit your review. Replace the angle-bracket placeholders before use.

```text
Use git-retell to explain <BASE> → <TARGET> as <NAME> in <WORKTREE>, with a
<LINES>-line budget and <CONTEXT> context lines. Read git-retell --help first.

Favor progressive refinement: show the end-to-end behavior early, then add
detail. Introduce variables, functions, and classes alongside their first
use, rather than as advance preparation. Use simple implementations or explicit
stubs when needed to fit usage and definition together, then refine them.

Make each step substantial and coherent, with a commit message explaining its
purpose and temporary limitations. Treat these as preferences, not rigid rules.

Preserve existing retellings. Reach the exact target tree, run git-retell
finish, and report the view command, expansion, and any check results or
limitations.
```

## Checks

`check NAME -- COMMAND ...` runs the exact argument vector, without a shell, on
each explanatory commit in a fresh detached worktree. It emits JSON containing
exit codes, stdout, stderr, and timeout results, then exits 1 if any check failed.
The base is not a step. Worktrees are removed after success, failure, or timeout;
on POSIX the timed-out process group is killed. Checks can install dependencies
or create files without modifying the authoring worktree. They execute project
code with your permissions; a worktree is not a security sandbox. Submodules and
Git LFS content are not automatically fetched. No checks run unless requested.

## Pure Git storage

For retelling `demo`, the only stored state is:

- `refs/heads/retell/demo`: the ordinary synthetic commit chain.
- `refs/retell/demo/base` and `refs/retell/demo/target`: pinned real commits.
- Repository config `retell.demo.budget`: the default line budget.
- Repository config `retell.demo.context`: the default context lines per hunk.

Branch movement cannot silently move the pinned endpoints. There is no tutorial
format or sidecar file. Commit messages should identify the synthetic nature
when read outside this CLI; every CLI slide explicitly labels it.
To share a history, include its endpoints, since the target may not be an ancestor
of the synthetic branch. A normal Git bundle works:

```sh
git bundle create demo.bundle refs/heads/retell/demo \
  refs/retell/demo/base refs/retell/demo/target
# In another repository:
git fetch /path/to/demo.bundle 'refs/heads/retell/demo:refs/heads/retell/demo' \
  'refs/retell/demo/*:refs/retell/demo/*'
git config retell.demo.budget 40
git config retell.demo.context 3
```

`start` refuses an existing retelling or branch. It never resets the main checkout.
To remove just an authoring worktree, use `git-retell finish NAME` (or `git
worktree remove PATH` for an unfinished retelling); the retelling stays
available and `resume` checks it out again. Use `git-retell delete NAME` to
remove the retelling's refs and settings too. Retellings are not merged back
into the real development branch.

## Recursive dogfood

The first experiment is `dogfood`, explaining this implementation from the
original scaffold. In the development repository, try:

```sh
git-retell validate dogfood
git-retell view dogfood
```

Its commits introduce simple versions before the final generalizations, then
add validation, viewing, checks, CLI guidance, and regression tests. All temporary
code must disappear by the pinned target. The history and endpoint refs are local
Git artifacts, so a normal clone needs the bundle or an explicit fetch of these
refs. The explanatory branch has no special dependency on an authoring script.

## Development

To contribute to this tool, use uv. Run `uv sync --locked` to install the locked
dependencies. The following command will establish the
virtual environment and run tests:

```sh
uv run pytest
```

Run type checking with:

```sh
uv run basedpyright
```

To run git-retell locally, use:

```sh
uv run git-retell
```

When running from source during retelling authoring, use the original checkout
so the tool remains available while the synthetic implementation is incomplete.

Tests exercise real temporary repositories and worktrees, including exact trees,
nonlinear histories, diff budgets, binary patches, unusual paths, check cleanup,
and terminal navigation. The MVP deliberately has no AST renderer, sidecars,
web server, automatic synthesis backend, or requirement that intermediate steps
pass.

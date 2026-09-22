# git-retell

[![PyPI](https://img.shields.io/pypi/v/git-retell.svg)](https://pypi.org/project/git-retell/)
[![Changelog](https://img.shields.io/github/v/release/wolfmanstout/git-retell?include_prereleases&label=changelog)](https://github.com/wolfmanstout/git-retell/releases)
[![Tests](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml/badge.svg)](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/wolfmanstout/git-retell/blob/main/LICENSE)

Synthetic Git histories for code review

Explain a real code transformation **B → H** with a synthetic Git history
**B → S1 → S2 → … → H**. Each commit is a slide; its message explains its diff.
An agent or human authors the steps. This CLI supplies the authoring worktree,
validation, metrics, optional checks, and terminal slideshow. No LLM API required.

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

### Try it from source

Use uv for local development. From a checkout of this repository:

```sh
uv sync --locked
uv run git-retell --help

# Commit the real change first; B and H must resolve to commits.
uv run git-retell start demo --base HEAD~1 --target HEAD \
  --worktree /tmp/retell-demo --budget 40

# In /tmp/retell-demo, use ordinary Git to author the explanation:
# edit files, git add ..., git commit -m 'Explain why this step exists'
# Repeat, amend, or rebase as needed. Finish at exactly H's tree.

# Run these from the original repository, using its installed tool:
uv run git-retell validate demo --json
uv run git-retell show demo --step 1
uv run git-retell view demo
uv run git-retell check demo --timeout 60 -- uv run pytest
```

Installing the CLI makes `git-retell` available while working in any repository.
When using `uv run` from source, run the tool from the original checkout to avoid
depending on the incomplete implementation in a synthetic step. All commands
explain their options with `--help`.

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

The renderer uses ordinary Git unified diffs with three context lines, headers,
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

The budget covers the standard three-context-line diff. Messages, navigation,
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
- `0`: reset context to three lines. Context persists across steps.
- `r`: redraw after resizing; `q`: quit.

Changing context returns to the top of the slide. The footer shows the step,
context (`U3`, `U6`, etc.), and visible line range. All message and diff lines
remain accessible, including wrapped lines. Context is a viewing preference;
validation, expansion, saved histories, and plain `show` output remain unchanged.
`show NAME --all` prints every slide for a pager or text export. Terminal controls
are visibly escaped and tabs expanded. The MVP budgets lines, not reading time.

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

For history `demo`, the only stored state is:

- `refs/heads/retell/demo`: the ordinary synthetic commit chain.
- `refs/retell/demo/base` and `refs/retell/demo/target`: pinned real commits.
- Repository config `retell.demo.budget`: the default line budget.

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
```

`start` refuses an existing history or branch. It never resets the main checkout.
To remove a finished authoring worktree, use `git worktree remove PATH`; the
history stays available. To delete the history as well, delete its branch and
both endpoint refs, then remove its `retell.demo` config section using ordinary
Git. Review histories are not merged back into the real development branch.

## Recursive dogfood

The first experiment is `dogfood`, explaining this implementation from the
original scaffold. In the development repository, try:

```sh
uv run git-retell validate dogfood
uv run git-retell view dogfood
```

Its commits introduce simple versions before the final generalizations, then
add validation, viewing, checks, CLI guidance, and regression tests. All temporary
code must disappear by the pinned target. The history and endpoint refs are local
Git artifacts, so a normal clone needs the bundle or an explicit fetch of these
refs. The explanatory branch has no special dependency on an authoring script.

## Development

To contribute to this tool, use uv. The following command will establish the
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

Tests exercise real temporary repositories and worktrees, including exact trees,
nonlinear histories, diff budgets, binary patches, unusual paths, check cleanup,
and terminal navigation. The MVP deliberately has no AST renderer, sidecars,
web UI, automatic synthesis backend, or requirement that intermediate steps pass.

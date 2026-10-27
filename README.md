# Git Retell

[![PyPI](https://img.shields.io/pypi/v/git-retell.svg)](https://pypi.org/project/git-retell/)
[![Changelog](https://img.shields.io/github/v/release/wolfmanstout/git-retell?include_prereleases&label=changelog)](https://github.com/wolfmanstout/git-retell/releases)
[![Tests](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml/badge.svg)](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/wolfmanstout/git-retell/blob/main/LICENSE)

Git Retell works with your coding agent to turn a monster code review into a
slideshow of small, incremental diffs.

Each slideshow is a *retelling*: an alternate Git history that ends at exactly
the same code as the real change, written purely to make that change easy to
digest. Your agent writes the narrative; Git Retell scaffolds the retelling,
validates that it reaches the exact final result, and shows it in a terminal or
browser viewer. If you've viewed a retelling, you've reviewed the code changes.

## Installation

Install Git Retell with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git-retell
```

Or use `pipx install git-retell` or `pip install git-retell`. Requires Git.

## Usage

Retellings take a lot of tokens, so the best time to make one is when a branch
is otherwise ready to merge. To keep those tokens out of your main conversation,
branch or fork the conversation with your agent and ask for the retelling
there. Here's a prompt to start from; edit the placeholders and the style to
suit your review:

```text
Use git-retell to explain <BASE> → <TARGET> as <NAME>.
Read git-retell --help first.

Favor progressive refinement: show the end-to-end behavior as early as
possible, then add detail in later steps. Prefer a crude working
prototype in the first step over a single complete feature. Introduce
variables, functions, and classes alongside their first use, rather than
as advance preparation. Write code in its final location and form when
it fits alongside its first use; if it doesn't, simplify it rather than
separating them, then refine it. Temporary code that is rewritten is
fine. Complete the implementation before introducing tests.

Make each step substantial and coherent, with a commit message
explaining its purpose and temporary limitations. Group a longer
retelling into chapters. Treat these as preferences, not rigid rules.

Preserve existing retellings. Reach the exact target tree, run
git-retell finish, and report the view command, expansion, and any test
results or limitations.
```

When the agent is done, view the retelling in your browser or terminal:

```bash
git-retell web NAME
```

```bash
git-retell view NAME
```

Press `?` in the web viewer for its controls. If your review turns up something
to fix, go back to your original conversation to make the change.

A few variations you might want:

- **Pull requests:** `start --pr 123` retells a GitHub pull request, fetching
  it with the [GitHub CLI](https://cli.github.com) and naming it `pr-123`. In
  the prompt, replace the first line with "Use git-retell to explain pull
  request 123."
- **Uncommitted work:** `start --to-uncommitted` (or `--to-staged`) retells
  changes you haven't committed yet.
- **Partial retellings:** `start --partial` lets the retelling leave out files
  such as lock files, generated code, or tests. Add a line to the prompt saying
  which files to skip.
- **Real commits:** `git-retell web --from main` shows the real commits on your
  branch in the same viewer, without making a retelling.
- **Testing each step:** `git-retell test NAME -- pytest` runs your tests on
  every step.
- **Sharing:** `git-retell web NAME -o NAME.html` writes a single
  self-contained file you can send to anyone.
- **Reviewing on your phone:** have your agent serve the retelling and send you
  the link. Add a line to the prompt such as "When done, serve it with
  git-retell web --serve --secret-url behind ngrok and give me the URL." The
  page has a Download button, so you can share the file from your phone too.

Run `git-retell --help` and `git-retell COMMAND --help` for everything else.

## Development

To contribute to this tool, first checkout the code. Then run the tests with
[uv](https://docs.astral.sh/uv/):

```bash
uv run pytest
```

To run Git Retell from source:

```bash
uv run git-retell --help
```

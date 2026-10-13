# Notes for agents

## Naming

Call the product "Git Retell" in prose, UI labels, and page titles. Use
`git-retell` only for the command, the package, and identifiers such as file
prefixes and storage keys.

## Where documentation goes

The README is for people deciding to use the tool: what it is, how to install
it, the suggested agent prompt, and a short tour of common usage. Keep it short.
Don't explain internals or restate options; `--help` is the reference, and it
is written for agents authoring retellings, so it should be complete and
precise. When adding a feature, document it in `--help` first, and mention it
in the README only if a typical user would reach for it.

Facts that can't be learned from reading the code, such as design intent, go
in code comments next to the code they explain, or here if they span the
project.

## Design intent

- The tool never generates explanations or calls an LLM. The agent writes the
  narrative; the tool handles scaffolding, validation, and viewing.
- The tool does not prescribe an explanatory style. Progressive refinement
  (end-to-end behavior first, definitions introduced alongside their first use)
  is the recommended style, and it lives in the README's suggested prompt, not
  in validation.
- Validation is the trust guarantee: a valid retelling ends at exactly the
  target tree, so viewing it means reviewing every change. Don't add anything
  that hides edits from the rendered diffs.
- Retellings supplement the real history rather than replacing it, and are
  never merged back into the real branch.

## Development

Run tests with `uv run pytest`. Pre-commit runs ruff and basedpyright.

During development, run `uv run git-retell ...` to use the checkout's code.
After committing to main, run `uv tool install . --reinstall` to refresh the
system-wide install.

When retelling a change to this repository, don't run `uv run git-retell` inside
the authoring worktree: it would run that step's partial code, not a working
tool. Run the installed `git-retell`, or `uv run` from the main checkout.

# git-retell

[![PyPI](https://img.shields.io/pypi/v/git-retell.svg)](https://pypi.org/project/git-retell/)
[![Changelog](https://img.shields.io/github/v/release/wolfmanstout/git-retell?include_prereleases&label=changelog)](https://github.com/wolfmanstout/git-retell/releases)
[![Tests](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml/badge.svg)](https://github.com/wolfmanstout/git-retell/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/wolfmanstout/git-retell/blob/main/LICENSE)

Synthetic Git histories for code review

## Installation

Install this tool using `pip` or `pipx`:

```bash
pip install git-retell
```

## Usage

For help, run:

```bash
git-retell --help
```

You can also use:

```bash
python -m git_retell --help
```

## Development

To contribute to this tool, use uv. The following command will establish the
venv and run tests:

```bash
uv run pytest
```

To run git-retell locally, use:

```bash
uv run git-retell
```

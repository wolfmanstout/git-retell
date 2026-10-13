"""Resolve a GitHub pull request to local commits, using the gh CLI for metadata."""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click

from .git import git


@dataclass
class PullRequest:
    number: int
    title: str
    base: str
    head: str


def gh(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["gh", *args], cwd=repo, capture_output=True, check=False
        )
    except FileNotFoundError:
        raise click.ClickException(
            "--pr needs the GitHub CLI (gh): https://cli.github.com"
        ) from None
    if result.returncode:
        raise click.ClickException(result.stderr.decode(errors="replace").strip())
    return result.stdout.decode()


def pull_request(repo: Path, pr: str) -> PullRequest:
    """Look up PR (a number, URL, or branch) and fetch its commits if missing.

    The base is the merge base of the PR's head and its base branch, so the
    range matches the changes GitHub shows for the pull request even if the
    base branch has moved on or was merged into the PR.
    """
    info = json.loads(
        gh(
            repo,
            "pr",
            "view",
            pr,
            "--json",
            "number,title,url,baseRefName,baseRefOid,headRefOid",
        )
    )
    number = info["number"]
    tips = [info["baseRefOid"], info["headRefOid"]]
    if not all(has_commit(repo, tip) for tip in tips):
        # Fetch into FETCH_HEAD only, leaving every local ref as it is. The
        # retelling's pinned refs then keep the fetched commits alive.
        git(
            repo,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            fetch_source(repo, info["url"]),
            f"refs/pull/{number}/head",
            f"refs/heads/{info['baseRefName']}",
        )
    for tip in tips:
        if not has_commit(repo, tip):
            raise click.ClickException(
                f"Could not fetch commit {tip} of pull request #{number}."
            )
    base = git(repo, "merge-base", *tips).strip()
    return PullRequest(number, info["title"], base, info["headRefOid"])


def has_commit(repo: Path, oid: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{oid}^{{commit}}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def fetch_source(repo: Path, pr_url: str) -> str:
    """A remote that points at the PR's repository, so fetching uses its auth.

    Falls back to the repository's HTTPS URL when no remote matches.
    """
    project = re.sub(r"^https?://|/pull/\d+/?$", "", pr_url).lower()
    for remote in git(repo, "remote").split():
        url = git(repo, "remote", "get-url", remote).strip()
        if remote_project(url) == project:
            return remote
    return f"https://{project}.git"


def remote_project(url: str) -> str:
    """Reduce a remote URL to host/owner/repo, e.g. git@host:o/r.git → host/o/r."""
    url = re.sub(r"^[a-z+]+://", "", url.lower())
    url = re.sub(r"^[^@/]*@", "", url)
    url = re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", url)
    url = re.sub(r"^([^/:]+):\d+/", r"\1/", url)
    return re.sub(r"\.git/?$|/$", "", url)

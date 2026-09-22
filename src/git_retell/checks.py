"""Optional quality checks run on disposable, detached worktrees."""

import os
import signal
import subprocess
import tempfile
from pathlib import Path

from .git import git
from .history import History


def check(history: History, command: tuple[str, ...], timeout: float) -> list[dict]:
    results = []
    for number, commit in enumerate(history.commits(), 1):
        with tempfile.TemporaryDirectory(prefix="git-retell-check-") as directory:
            path = Path(directory) / "tree"
            git(history.repo, "worktree", "add", "--detach", str(path), commit)
            try:
                result = run_check(path, command, timeout)
                results.append({"step": number, "commit": commit, **result})
            finally:
                git(history.repo, "worktree", "remove", "--force", str(path))
    return results


def stop(process: subprocess.Popen) -> None:
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()


def run_check(path: Path, command: tuple[str, ...], timeout: float) -> dict:
    try:
        with subprocess.Popen(
            command,
            cwd=path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=os.name == "posix",
        ) as process:
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                stop(process)
                stdout, stderr = process.communicate()
                if isinstance(error, KeyboardInterrupt):
                    raise
                timed_out = True
                stderr += f"\nCheck exceeded {timeout:g} seconds."
            return {
                "returncode": process.returncode,
                "passed": process.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": timed_out,
            }
    except OSError as error:
        return {
            "returncode": None,
            "passed": False,
            "stdout": "",
            "stderr": str(error),
            "timed_out": False,
        }

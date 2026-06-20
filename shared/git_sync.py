"""
GitSync — lightweight git auto-commit / push utility
=====================================================
Scheduled every N cycles (default: 6) when ``GIT_AUTO_SYNC=True``.
All operations are fire-and-forget — failures are logged at DEBUG
level and NEVER block the trading pipeline.

Zero ``import backend.`` — uses plain ``subprocess``.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


def _run_git(args: list, cwd: str, timeout: int = 15) -> Optional[str]:
    """Run a git command, return stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.debug(
                f"git {' '.join(args[:3])} exit {result.returncode}: "
                f"{result.stderr.strip()[:120]}"
            )
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        logger.debug("git executable not found — skipping sync")
        return None
    except subprocess.TimeoutExpired:
        logger.debug(f"git {' '.join(args[:3])} timed out after {timeout}s")
        return None
    except Exception as exc:
        logger.debug(f"git {' '.join(args[:3])} error: {exc}")
        return None


def git_sync(project_root: str = ".") -> bool:
    """Perform a full git add → commit → pull → push cycle.

    Args:
        project_root: Path to the git working directory.

    Returns:
        True on success, False on any failure.
    """
    root: Path = Path(project_root).resolve()
    if not (root / ".git").exists():
        logger.debug(f"No .git directory at {root} — skipping git sync")
        return False

    cwd: str = str(root)
    timestamp: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. git add -A
    if _run_git(["add", "-A"], cwd) is None:
        return False

    # 2. Check if there are staged changes.
    diff = _run_git(["diff", "--cached", "--quiet"], cwd)
    has_changes: bool = diff is None
    if not has_changes:
        # No changes to commit — but we can still try pull/push.
        logger.debug("git_sync: no changes to commit")
        has_changes = False

    # 3. git commit (only if changes exist)
    if has_changes:
        commit_msg: str = f"auto: pipeline sync {timestamp}"
        _run_git(["commit", "-m", commit_msg], cwd)

    # 4. git pull --rebase
    _run_git(["pull", "--rebase", "origin"], cwd, timeout=30)

    # 5. git push
    result = _run_git(["push", "origin"], cwd, timeout=30)
    if result is not None:
        logger.info(f"✅ Git sync completed at {timestamp}")
        return True

    return False

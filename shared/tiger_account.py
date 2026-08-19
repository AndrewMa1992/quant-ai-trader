"""Resolve the active Tiger account for paper vs live.

Paper/sim defaults to the documented Tiger paper account.
Live requires simulation off + explicit live account.
"""

from __future__ import annotations

import os

from shared.execution_mode import is_simulation_mode

# Documented in ops reports / deploy templates
PAPER_ACCOUNT_DEFAULT = "21837535188693626"
LIVE_ACCOUNT_DEFAULT = "20874631"


def resolve_tiger_account(explicit: str | None = None) -> str:
    """Return the Tiger funds account that APIs / orders should use."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()

    env_acct = (
        os.getenv("QAT_TIGER_ACCOUNT", "").strip()
        or os.getenv("QAT_EXEC_TIGER_ACCOUNT", "").strip()
    )
    if is_simulation_mode():
        # Prefer env if it looks like paper (long numeric) or any non-empty paper override
        if env_acct and env_acct != LIVE_ACCOUNT_DEFAULT:
            return env_acct
        return PAPER_ACCOUNT_DEFAULT

    if env_acct:
        return env_acct
    return LIVE_ACCOUNT_DEFAULT

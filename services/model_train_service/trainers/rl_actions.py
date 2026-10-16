"""Cash-only actions for the PPO trading environment.

0 = hold, 1 = buy to a long, 2 = sell that long back to cash.
Action 2 never opens a short.
"""

from __future__ import annotations


def apply_position(position: float, action: int) -> float:
    """Return the next position, which is only flat (0) or long (1)."""
    pos = 1.0 if float(position) > 0 else 0.0
    act = int(action)
    if act == 1 and pos == 0.0:
        return 1.0
    if act == 2 and pos > 0:
        return 0.0
    return pos

"""Print Tiger credential presence (never prints private key material).

Usage (on Lightsail / GPU PC)::

    python scripts/extract_tiger_credentials.py
"""

from __future__ import annotations

import os
from pathlib import Path

from configs.settings import settings


KNOWN_FROM_REPO = {
    "tiger_id": "20159337",
    "paper_account": "21837535188693626",
    "live_account": "20874631",
}


def _mask(v: str) -> str:
    if not v:
        return "(empty)"
    if len(v) <= 4:
        return "****"
    return f"{v[:2]}…{v[-2:]} (len={len(v)})"


def main() -> None:
    print("=== Tiger credentials (extracted / detected) ===")
    print(f"  known tiger_id (repo):     {KNOWN_FROM_REPO['tiger_id']}")
    print(f"  known paper account:        {KNOWN_FROM_REPO['paper_account']}")
    print(f"  known live account:         {KNOWN_FROM_REPO['live_account']}")
    print()
    print("=== Active settings (env / .env) ===")
    print(f"  TIGER_ID:                   {settings.TIGER_ID or '(empty)'}")
    print(f"  TIGER_ACCOUNT:              {settings.TIGER_ACCOUNT or '(empty)'}")
    print(f"  TIGER_LICENSE:              {_mask(settings.TIGER_LICENSE)}")
    print(f"  TIGER_PAPER_TRADING:        {settings.TIGER_PAPER_TRADING}")
    print(f"  TIGER_PRIVATE_KEY_PATH:    {settings.TIGER_PRIVATE_KEY_PATH}")
    print(f"  TIGER_PRIVATE_KEY set:      {bool(settings.TIGER_PRIVATE_KEY)}")

    key_path = Path(os.path.expanduser(settings.TIGER_PRIVATE_KEY_PATH))
    props = Path(os.path.expanduser("~/.tigeropen"))
    print()
    print("=== On-disk key material ===")
    print(f"  PEM exists: {key_path} → {key_path.is_file()}")
    if key_path.is_file():
        raw = key_path.read_text(encoding="utf-8", errors="ignore")
        print(f"  PEM size:  {len(raw)} bytes; has BEGIN marker: {'BEGIN' in raw}")
    print(f"  ~/.tigeropen dir: {props} → {props.is_dir()}")
    if props.is_dir():
        for p in sorted(props.iterdir()):
            print(f"    - {p.name} ({p.stat().st_size} bytes)")

    missing = []
    if not (settings.TIGER_ID or KNOWN_FROM_REPO["tiger_id"]):
        missing.append("TIGER_ID")
    if not key_path.is_file() and not settings.TIGER_PRIVATE_KEY and not props.is_dir():
        missing.append("private key (certs/tiger_private_key.pem or ~/.tigeropen)")
    print()
    if missing:
        print("MISSING for Tiger connect:", ", ".join(missing))
        print("Place RSA key on Lightsail at certs/tiger_private_key.pem then restart pipeline.")
    else:
        print("OK: enough material for Tiger SDK connect attempt.")


if __name__ == "__main__":
    main()

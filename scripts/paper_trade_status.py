"""Quick status: can we paper-trade? which DB? is Redis up? model sizes?"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> None:
    from configs.settings import settings
    from shared.execution_mode import get_execution_mode, is_simulation_mode

    print("=== Paper / execution ===")
    print(f"  EXECUTION_MODE={get_execution_mode()}")
    print(f"  SIMULATION={is_simulation_mode()}")
    print(f"  TIGER_PAPER_TRADING={settings.TIGER_PAPER_TRADING}")
    print(f"  INITIAL_CAPITAL={settings.TRADING_INITIAL_CAPITAL}")
    print(f"  Can paper trade locally: YES (PortfolioManager fills)")
    print(
        f"  Can paper trade via Tiger API: "
        f"{'YES if Tiger connected + credentials' if settings.TIGER_PAPER_TRADING else 'NO (flag false)'}"
    )

    print("\n=== Database ===")
    print(f"  POSTGRES_URL={settings.POSTGRES_URL}")
    db_kind = "sqlite" if "sqlite" in settings.POSTGRES_URL.lower() else "postgres"
    print(f"  Kind: {db_kind}")
    if db_kind == "sqlite":
        from shared.database.engine import optimize_sqlite_file

        optimize_sqlite_file("data/quant_trader.db")
        p = ROOT / "data" / "quant_trader.db"
        print(f"  File: {p} exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")

    print("\n=== Redis ===")
    print(f"  REDIS_URL={settings.REDIS_URL}")
    try:
        from shared.redis_client import get_redis

        r = await get_redis()
        await r.connect()
        print(f"  mode={r.mode} degraded={r.is_degraded}")
        if not r.is_degraded:
            await r.cache_set("qat:healthcheck", {"ok": True}, ttl=30)
            print("  ping+set: OK")
        else:
            print("  using in-memory degrade — install Redis/Memurai for persistence")
    except Exception as e:
        print(f"  ERROR: {e}")

    print("\n=== Models ===")
    models = list((ROOT / "data" / "models").glob("*"))
    for m in sorted(models):
        if m.is_file():
            print(f"  {m.name:32} {m.stat().st_size/1e6:.2f} MB")
    try:
        from services.model_train_service.config import train_config

        print(
            f"  Train defaults: d_model_gpu={train_config.TRANSFORMER_D_MODEL_GPU} "
            f"layers={train_config.TRANSFORMER_N_LAYERS} "
            f"tcn_ch={train_config.TCN_CHANNELS} tft_h={train_config.TFT_HIDDEN_DIM}"
        )
    except Exception as e:
        print(f"  train_config: {e}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())

# Continuous paper trading ops (Lightsail + Tiger)

Honest scope: this is **institutional-grade retail automation**, not RenTec.
No system maximizes profit every day. Goal = survive, trade size correctly, keep
running, compound edge from models that are regularly retrained.

## What was hardened (this upgrade)

| Area | Change |
|------|--------|
| $1700 sizing | `shared/capital_policy.py` — min ticket ~$25–75, max name 35%, deploy ~85% |
| Rebalance | Mark-to-market weights + explicit qty (not avg_cost / discarded qty) |
| Sessions | `zoneinfo` calendars; prefer open markets; US 24h via `QAT_US_24H_TRADING` |
| Tiger paper | `QAT_TIGER_PAPER_TRADING=true` → place paper orders then mirror local book |
| Risk persist | `data/risk_state.json` survives restarts |
| Model age | >14d → higher threshold + half conviction; reload every 50 cycles |
| Daily trades | 24 (was 5) for five-market rotation |

## Continuous run (Lightsail)

```powershell
cd C:\quant-ai-trader
git fetch origin
git reset --hard origin/cursor/quant-upgrade-a75f

# Ensure .env has:
# QAT_TRADING_SIMULATION_MODE=true
# QAT_EXECUTION_MODE=paper
# QAT_TRADING_INITIAL_CAPITAL=1700
# QAT_TIGER_PAPER_TRADING=true
# QAT_ENABLED_MARKETS=US,HK,SG,AU,NZ
# Tiger credentials: QAT_TIGER_ID / QAT_TIGER_ACCOUNT / key path

.\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f -EnableDataDownload
.\scripts\windows_cd_deploy.ps1 -Branch cursor/quant-upgrade-a75f -Force
.\scripts\windows_pipeline_watchdog.ps1   # optional: keep pipeline process up
```

Home GPU already has `QAT-Local-TrainSync` at 03:00 — keep models fresh.

## Still not “perfect”

- No alternative data / L2 / co-location
- Factor columns in pipeline Step2 still partially anonymous (`f0..`) — alpha quality gap
- Live FX rates still mostly static
- Tiger credentials must be valid for paper account routing
- Markets closed (non-US) still need liquidity/lot awareness

## Kill / promote

See `docs/INSTITUTIONAL_STANDARDS.md`. Live requires sim off + mode live + promotion approve.

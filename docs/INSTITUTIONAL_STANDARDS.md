# Institutional Standards Upgrade

**Branch intent**: Align `quant-ai-trader` with *operating practices* of top quant funds (risk single source of truth, durable halt, promotion gates, audit, TCA, model staging) — not claim parity with RenTec / Two Sigma / Citadel alpha stack.

See also: `docs/gap-analysis-vs-top-funds.md` for the full gap matrix.

---

## What this upgrade delivers

| Practice | Top-fund analogue | Implemented here |
|----------|-------------------|------------------|
| Durable kill switch | Desk-wide halt until human reset | `shared/kill_switch.py` → `cache/kill_switch.json`; RiskGate Gate 0; RiskManager CB engage; Tiger live block; API `/kill-switch` |
| Paper → live promotion | Ops checklist + dual control | `shared/live_promotion.py`; live orders require sim off + `QAT_EXECUTION_MODE=live` + approve record |
| Simulation lock | Default sim / no accidental live | `QAT_TRADING_SIMULATION_MODE=true` default; `shared/execution_mode.py` |
| Risk limits SSoT | Central risk book | `configs/risk_limits.py` → RiskManager thresholds + RiskGate exposure |
| Exposure gates | Gross / net / single-name | RiskGate Gate 5 vs `RISK_LIMITS` |
| Audit trail | Trade / risk JSONL for compliance | `shared/audit_trail.py` → `cache/audit/` |
| TCA (lite) | Arrival vs fill, IS bps, ADV participation | `services/execution_service/live/tca.py` attached on fills |
| Model registry gate | Staging ≠ Production auto | MLflow `register_model` stays **Staging** until `promote_to_production()` |
| Optimizer hygiene | Turnover + cash buffer | `ConstraintSystem.build_cvxpy` turnover + `sum(w) ≤ 1` |

---

## Live trading checklist (must all be true)

1. `QAT_TRADING_SIMULATION_MODE=false`
2. `QAT_EXECUTION_MODE=live`
3. `POST /api/v2/risk/live-promotion/approve` with checklist keys:
   - `paper_soak_days`
   - `risk_limits_loaded`
   - `kill_switch_clear`
   - `models_in_staging_or_prod`
   - `operator_ack`
4. Kill switch **not** engaged
5. Tiger connected (for broker path)

Without (3), TigerExecutor forces **paper fills** even if mode string is `live`.

---

## Still not RenTec (honest remaining gaps)

| Area | Status |
|------|--------|
| Alternative data / tick / L2 | Not in scope |
| 1000+ factor factory + auto discovery | Not in scope |
| PIT universe / corporate actions / survivorship | Open P0 research debt |
| Full stress library + LVaR | Partial (limits exist; scenario suite not) |
| Multi-PB / SOR / dark pools | Not applicable at this scale |
| backend/ vs services/ dual tree | P2 architecture debt |
| Deflated Sharpe / purged CV | Research backlog |

---

## Operator API surface

```
GET  /api/v2/risk/kill-switch
POST /api/v2/risk/kill-switch/engage   {"reason","engaged_by"}
POST /api/v2/risk/kill-switch/reset    {"reset_by"}

GET  /api/v2/risk/live-promotion
POST /api/v2/risk/live-promotion/approve  {"operator","checklist":{...}}
POST /api/v2/risk/live-promotion/revoke  {"operator","reason"}
```

Audit files: `cache/audit/cycle_YYYYMMDD.jsonl`, `risk_reject_*.jsonl`, `order_*.jsonl`, `tca_*.jsonl`.

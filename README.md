# Quant AI Trader

AI-powered multi-market paper trading system. FastAPI microservices, Vue 3 dashboard, PatchTST / GBDT / TCN / TFT models, and Tiger Brokers OpenAPI.

Paper mode is the default. Live account `20874631` is not used in simulation.

## Stack

Python 3.11+ · FastAPI · Vue 3 + Vite · PyTorch · scikit-learn · Tiger OpenAPI (`tigeropen`) · SQLite

## Docker (paper · Linux)

```bash
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh
# API + SPA  http://localhost:8001
# Optional UI http://localhost:5180
```

See [DEPLOY.md](./DEPLOY.md). Compose forces `QAT_EXECUTION_MODE=paper`.

## Windows Server / Lightsail (native, no Docker)

```powershell
git checkout cursor/quant-upgrade-a75f
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\windows_deploy.ps1 -OpenFirewall
# Public UI: http://<public-ip>:8001/
```

See [DEPLOY_WINDOWS.md](./DEPLOY_WINDOWS.md) for RDP, firewall ports, start/stop, boot autostart, and scheduled deploy. Run `windows_install_autostart.ps1 -RunNow` once on the server to keep the stack up and pull updates.

Current paper box: `http://3.106.139.233:8001/` (gateway SPA). Paper Tiger account: `21837535188693626`.

## Capabilities

| Module | Tech | What it does |
|--------|------|----------------|
| Price forecast | PyTorch PatchTST / TCN / TFT | Multi-horizon forecasts with quantile bands |
| Tabular ensemble | LightGBM / XGBoost / CatBoost | Daily signal from engineered factors |
| PPO (optional) | Stable-Baselines3 | Position sizing / Sharpe-oriented policy |
| Sentiment | FinBERT | News / market-tone score |
| Signal fusion | Weighted ensemble | Dynamic model weights, Kelly-style sizing |
| Risk | VaR, drawdown, position caps | Hard limits before orders leave the book |
| Execution | Paper broker + Tiger OpenAPI | Sync cash, positions, and fills from Tiger paper |
| Backtest | Historical replay | Walk-forward reports |
| Frontend | Vue 3, ECharts, Pinia | Live dashboard, orders, risk, data sync |

## Layout

```
quant-ai-trader/
├── api_gateway/                 # FastAPI gateway :8001 (serves SPA + /api/v2)
├── services/
│   ├── data_service/            # quotes, ingest, Tiger quote client
│   ├── factor_service/          # feature pipeline
│   ├── model_train_service/     # training jobs
│   ├── model_infer_service/     # live inference
│   ├── risk_service/            # risk checks
│   └── execution_service/       # orders, Tiger trade client, paper book
├── shared/                      # Tiger SDK helper, persist, pipeline glue
├── configs/                     # QAT_ settings (pydantic-settings)
├── frontend/                    # Vue 3 app (built dist served by gateway)
├── scripts/                     # Windows / Docker deploy and watchdogs
├── data/                        # SQLite, daily bars, model checkpoints
└── trading_pipeline.py          # paper trading loop
```

## Quick start (dev)

Requirements: Python 3.11+, Node.js 18+. Tiger credentials are optional for local paper.

```bash
python -m pip install -e .
cd frontend && npm install && npm run build && cd ..
python -m uvicorn api_gateway.main:app --host 0.0.0.0 --port 8001
# UI: http://localhost:8001/
```

Windows one-shot: `scripts\windows_deploy.ps1`. Linux/macOS helper: `./start.sh` if present.

## Tiger Brokers OpenAPI

Paper / demo trading uses **production** OpenAPI with the paper account id (not the sandbox environment).

1. Create an app on the [Tiger OpenAPI console](https://quantit.tigerfintech.com/openapi)
2. Save the RSA private key as `certs/tiger_private_key.pem` (gitignored)
3. Set in `.env`:
   - `QAT_TIGER_ID`
   - `QAT_TIGER_ACCOUNT` (paper: `21837535188693626`)
   - `QAT_TIGER_PRIVATE_KEY_PATH`
   - `QAT_TIGER_LICENSE=TBSG` (retry `TBHK` if connect fails)
   - `QAT_TIGER_SANDBOX=false`
   - `QAT_TIGER_PAPER_TRADING=true`
   - `QAT_EXECUTION_MODE=paper`
4. Install the SDK: `pip install "tigeropen>=3.5.8"`

Do not switch `QAT_EXECUTION_MODE` to live until promotion gates pass.

## Model path

```
market data → PatchTST / TCN / TFT / GBDT ──┐
news / tone  → FinBERT                     ──┼──→ ensemble → risk → Tiger / paper fill
portfolio    → optional PPO fine-tune      ──┘
```

## License

Proprietary (see `pyproject.toml`).

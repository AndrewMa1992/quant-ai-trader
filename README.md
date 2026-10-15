# Quant AI Trader

Paper-trading system for US, Hong Kong, Singapore, Australia, and New Zealand equities. Market data is turned into factors, several models vote on a signal, risk limits size the order, and the fill is sent to a Tiger Brokers paper account. A Vue 3 dashboard shows the book, the models, and the server logs.

Version 2.1. Simulation is the default. Orders stay on the Tiger paper account until execution mode is changed on purpose.

## Trading loop

```
quotes and factors
        │
        ▼
PatchTST · TCN · TFT · gradient-boosted trees
        │
        ▼
ensemble weights and position size
        │
        ▼
risk gate (VaR, drawdown, position caps)
        │
        ▼
Tiger Brokers paper order
        │
        ▼
positions, cash, and fills synced back to the dashboard
```

FinBERT can score news tone. An optional PPO policy can adjust size. Both sit behind the same risk gate.

## Stack

| Layer | Choice |
| --- | --- |
| API | FastAPI gateway on port 8001, WebSocket push |
| Services | Data, factors, training, inference, risk, execution |
| Models | PyTorch PatchTST / TCN / TFT, LightGBM / XGBoost / CatBoost |
| Broker | Tiger OpenAPI (`tigeropen`), paper account on the production API |
| Store | SQLite by default; Postgres and Redis in Docker |
| UI | Vue 3, TypeScript, Vite, Pinia, ECharts |

Redis falls back to an in-memory cache when it is down, so the gateway still serves the dashboard.

## Dashboard

The gateway serves the built UI at `/`.

| Page | What you see |
| --- | --- |
| Dashboard | Net asset value, positions, signals |
| Factors / Models | Feature pipeline and model status |
| Risk / Portfolio | Limits, exposures, optimizer |
| Backtest | Historical replay |
| Execution / Orders | Paper orders and Tiger sync |
| Data / Sync | Bars and ingestion status |
| Logs | Server log files over `GET /api/v2/logs` |

## Run with Docker

Requires Docker Engine and Compose. The stack starts in paper mode.

```bash
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh
```

| URL | Service |
| --- | --- |
| http://localhost:8001 | Gateway and dashboard |
| http://localhost:8001/docs | API docs |
| http://localhost:5180 | Frontend container |

Details and the MLflow profile are in [DEPLOY.md](./DEPLOY.md). Stop with `./scripts/docker_down.sh`.

## Run on Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\windows_deploy.ps1 -OpenFirewall
```

The public site listens on port 80 and forwards to the gateway. Port 8080 forwards to the frontend on 5180. RDP, firewall rules, and boot tasks are in [DEPLOY_WINDOWS.md](./DEPLOY_WINDOWS.md).

A Windows host that has run `scripts\windows_auto_deploy.ps1 -InstallTask` tracks GitHub `main`. Every two minutes it fetches `origin/main`. A new commit resets the checkout and redeploys the paper stack. `.env`, `certs\`, logs, and local market data are left in place.

## Local development

Python 3.11+ and Node.js 18+. Tiger credentials are optional until you query the broker.

```bash
python -m pip install -e ".[dev]"
cd frontend && npm install && npm run build && cd ..
python -m uvicorn api_gateway.main:app --host 0.0.0.0 --port 8001
```

Open http://localhost:8001/.

## Tiger Brokers

Paper trading uses the production OpenAPI host with the paper account, not the sandbox environment.

1. Create an app in the [Tiger OpenAPI console](https://quantit.tigerfintech.com/openapi).
2. Save the RSA private key as `certs/tiger_private_key.pem`. That path is gitignored.
3. Put the following in `.env`:

```
QAT_TIGER_ID=
QAT_TIGER_ACCOUNT=21837535188693626
QAT_TIGER_PRIVATE_KEY_PATH=certs/tiger_private_key.pem
QAT_TIGER_LICENSE=TBSG
QAT_TIGER_SANDBOX=false
QAT_TIGER_PAPER_TRADING=true
QAT_EXECUTION_MODE=paper
QAT_TRADING_SIMULATION_MODE=true
```

If the license region rejects the connection, try `TBHK`. Install the SDK with `pip install "tigeropen>=3.5.8"` when it is not already in the environment. Leave `QAT_EXECUTION_MODE` on `paper` until a separate promotion step says otherwise.

## Layout

```
quant-ai-trader/
├── api_gateway/            # gateway, health, logs, WebSocket
├── services/               # data, factor, train, infer, risk, execution
├── shared/                 # Tiger client, persistence, Redis
├── configs/                # pydantic settings and risk limits
├── frontend/               # Vue 3 TypeScript app
├── scripts/                # Docker, Windows deploy, auto-deploy
├── trading_pipeline.py     # scheduled paper cycle
└── data/                   # local bars, SQLite, checkpoints (not all committed)
```

## License

Proprietary. See `pyproject.toml`.

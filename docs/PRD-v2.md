# PRD: Quant AI Trader v2

| Item | Content |
|------|------|
| Product | quant-ai-trader v2 — institutional-grade AI trading system |
| Version | v2.0 |
| Status | Pending review |
| Language | English |
| Tech stack | Python + FastAPI + Vue 3 + PyTorch + MLflow |

---

## 1. Project Information

- **Project Name**: `quant_ai_trader_v2`
- **Programming Language**: Python 3.11+ (Backend) + TypeScript/Vue 3 (Frontend)
- **Requirement restatement**: Rebuild the entire quantitative trading system to the standard of leading quantitative funds (Renaissance Technologies / Two Sigma / Citadel / D.E. Shaw class), covering eight modules: factor engineering, AI/ML engine, risk model, portfolio optimization, backtest engine, execution system, data pipeline, and infrastructure.

---

## 2. Product Definition

### 2.1 Product Goals

1. **Institutional-grade factor research platform**: Provide a systematic research framework for 100+ factors, supporting factor IC/IR analysis, correlation matrices, decay curves, automated discovery, and neutralization, so that factor-research efficiency and depth reach professional quant-team standards.
2. **Multi-model AI prediction engine**: Integrate four model families — GBDT, deep learning, reinforcement learning, and market-regime identification — with dynamic Bayesian weighting for adaptive signal fusion, plus GPU-accelerated training and distributed hyperparameter optimization.
3. **End-to-end production trading pipeline**: From data collection -> factor computation -> model prediction -> risk budgeting -> portfolio optimization -> order execution -> performance attribution, with the full chain auditable, reproducible, and independently deployable.

### 2.2 User Stories

| # | Role | Need | Value |
|---|------|------|------|
| US-1 | Quant researcher | I want a unified platform for factor research: batch-compute 100+ factors, view IC decay curves and factor-correlation heatmaps, so I can quickly screen effective alpha factors | Raise factor-research efficiency from manual Excel to a systematic platform |
| US-2 | Strategy developer | I want one-click multi-model (XGBoost / LightGBM / Transformer / TFT) training + Optuna hyperparameter search + walk-forward backtest validation, with a complete performance report produced automatically | Shorten the strategy iteration cycle from days to hours |
| US-3 | Risk manager | I want real-time Barra style-factor exposures, VaR / CVaR / Expected Shortfall, and sector concentrations, with immediate alerts when risk limits are breached | Move risk monitoring from after-the-fact inspection to ex-ante warning |
| US-4 | Trader | I want the portfolio optimizer to compute optimal holdings from my constraints (single-name weight caps, sector concentration, turnover limits) and automatically slice orders via TWAP / VWAP | Raise execution quality from manual dispersion to algorithmic optimization |
| US-5 | Site reliability / ops | I want each module (data / training / inference / execution) independently deployed and monitored, model versions managed in MLflow, and anomalies pushed immediately via Slack / WeChat Work | Raise availability from personal scripts to production-grade services |

---

## 3. Technical Specification

### 3.1 Requirements Pool

#### P0 — Core capabilities (must ship; otherwise v2 is not viable)

| ID | Module | Requirement | Acceptance criteria |
|----|------|----------|----------|
| P0-1 | Data pipeline | Multi-source fusion: yfinance + Tiger API + EODHD + FRED (macro), covering five markets: US (500+), HK (200+), SG (30+), AU (50+), NZ (20+) | Daily data coverage >= 800 names; minute-level coverage >= 500 names; data-quality checks automatically flag missing / anomalous values |
| P0-2 | Data pipeline | Real-time stream + historical storage: WebSocket pushes live quotes into Redis Stream; historical OHLCV in Parquet + SQLite metadata index | Latency < 500 ms; historical queries < 2 seconds |
| P0-3 | Factor engineering | Factor computation framework: technical (50+), fundamental (30+), alternative (20+), microstructure (10+); unified Factor base class; vectorized batch computation | Full-universe daily factor computation < 30 seconds |
| P0-4 | Factor engineering | Factor evaluation: IC mean / std / IR, factor correlation matrix, factor decay curves, stratified backtests (quantile-portfolio returns), Fama-MacBeth regression | Each factor automatically produces an evaluation report |
| P0-5 | AI engine | GBDT models: one of XGBoost / LightGBM / CatBoost, GPU-accelerated, outputting feature importance + SHAP explanations | AUC > 0.55 (daily directional prediction) |
| P0-6 | AI engine | Deep-learning models: Transformer (d_model >= 512) + TCN + TFT (Temporal Fusion Transformer), supporting multi-step forecasts | At least one DL model with Sharpe > 1.0 (backtest) |
| P0-7 | AI engine | Walk-forward training: rolling train / validation windows to avoid look-ahead bias; time-series cross-validation | Train and validation strictly chronological; no future-information leakage |
| P0-8 | Risk model | Barra multi-factor risk model: USE4 / CNE5-style style-factor exposures, factor covariance matrix, specific-risk estimation | Factor exposures cover: Beta / Size / Value / Momentum / Quality / Volatility / Growth / Leverage / Liquidity |
| P0-9 | Risk model | Covariance estimation: Ledoit-Wolf shrinkage + exponentially weighted decay (60-day half-life) | Matrix condition number < 1e6 (numerical stability) |
| P0-10 | Risk model | Real-time VaR / CVaR / Expected Shortfall: parametric + historical simulation + Monte Carlo, cross-validated | 95% / 99% confidence, daily refresh |
| P0-11 | Portfolio optimization | Mean-Variance Optimization (Markowitz): maximize Sharpe from estimated return vector and covariance | Solver < 5 seconds (<= 500 names) |
| P0-12 | Portfolio optimization | Black-Litterman: fold model signals in as subjective views on prior equilibrium returns to produce posterior optimal weights | Support absolute views + relative views |
| P0-13 | Portfolio optimization | Constraint system: single-name weight caps, sector concentration, turnover caps, cash floor, short-sale limits, optional beta-neutrality | All constraints satisfied simultaneously; no violations |
| P0-14 | Backtest engine | Event-driven backtest: minute-level precision; three event queues (market / signal / trade) | 1-year backtest < 10 minutes (500 names) |
| P0-15 | Backtest engine | Matching model: slippage (Almgren-Chriss class), impact cost, limit / market order simulation | Slippage estimate error < 20% |
| P0-16 | Execution | TWAP / VWAP / POV order-slicing algorithms | Average daily slippage < 5 bp |
| P0-17 | Execution | Real-time P&L tracking + circuit breaker (halt trading if daily loss > 5%) | Circuit-breaker trigger to execution halt < 1 second |
| P0-18 | Infrastructure | Modular architecture: six independent services — data, factor compute, model training, model inference, portfolio optimization, order execution | Each service independently deployable via Docker Compose |

#### P1 — Important capabilities (materially improve performance / experience)

| ID | Module | Requirement | Acceptance criteria |
|----|------|----------|----------|
| P1-1 | Factor engineering | Automated factor discovery: genetic programming (gplearn) + symbolic regression; weekly candidate factor pool | >= 100 candidate factors per week; automatically drop factors with IC < 0.02 |
| P1-2 | Factor engineering | Factor neutralization: industry neutralization (dummy-variable regression) + size neutralization + style neutralization | After neutralization, factor correlation with size / industry < 0.05 |
| P1-3 | AI engine | Market-regime identification: HMM hidden-state classification (bull / bear / range / high-vol) + GARCH volatility forecasts | Regime classification accuracy >= 70% |
| P1-4 | AI engine | Dynamic model weights: Bayesian weighting from recent performance (rolling 60-day Sharpe / IC) | Dynamic weighting Sharpe improvement >= 0.1 vs. fixed weights |
| P1-5 | AI engine | Distributed hyperparameter search: Optuna + multi-GPU parallelism, supporting >= 100 automatic trials | Hyperparameter search time <= 4 hours (single model) |
| P1-6 | AI engine | Reinforcement-learning engine: PPO + SAC, reward = risk-adjusted return | RL strategy Sharpe >= 1.0 (backtest) |
| P1-7 | Risk model | Stress testing and scenario analysis: replay of historical extremes (2008 / 2020 / 2022) + custom scenarios | At least 5 preset historical scenarios |
| P1-8 | Portfolio optimization | Risk Parity + Maximum Diversification as alternative objective functions | Solver < 5 seconds |
| P1-9 | Backtest engine | Performance attribution: Brinson + factor attribution, separating alpha vs. beta returns | Attribution report generated automatically |
| P1-10 | Execution | Tiger Brokers OpenAPI live integration: US / HK dual-market order placement, position query, order-status sync | Order-ack latency < 3 seconds |
| P1-11 | Infrastructure | MLflow model versioning + experiment tracking | Every training run automatically records params / metrics / model artifacts |
| P1-12 | Infrastructure | Alerting: Slack + WeChat Work + email, with custom alert rules | Alert latency < 30 seconds |

#### P2 — Enhancement capabilities (nice-to-have)

| ID | Module | Requirement |
|----|------|----------|
| P2-1 | Factor engineering | Factor freshness monitoring: automatically detect IC decay; mark a factor "expired" and recommend replacement when IC falls below a threshold |
| P2-2 | AI engine | Integrate TabNet / N-BEATS / Autoformer as alternative models |
| P2-3 | Risk model | Risk attribution: decompose portfolio risk into factor risk + specific risk + interaction terms |
| P2-4 | Portfolio optimization | Transaction-cost-aware optimal execution: embed the impact-cost model in the objective |
| P2-5 | Backtest engine | Multi-asset backtests: equities + ETFs + futures in the same run |
| P2-6 | Execution | Smart routing: choose the best market maker by liquidity / spread |
| P2-7 | Data pipeline | Alternative-data ingest: SEC filing sentiment, Reddit / Twitter sentiment, supply-chain data |
| P2-8 | Infrastructure | Kubernetes deployment + Prometheus / Grafana monitoring dashboards |
| P2-9 | Frontend | Vue 3 dashboard v2: factor-analysis panel, portfolio-optimization panel, live risk dashboard, backtest-report panel |
| P2-10 | Frontend | Mobile: WeChat mini-program or PWA for live P&L and alerts |

### 3.2 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         API Gateway (FastAPI)                         │
├──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────────────────┤
│ Data │Factor│Model │Model │Risk  │Portf.│Exec. │  Infrastructure    │
│Svc   │Calc  │Train │Infer │Model │Opt   │Engine│                    │
│      │      │      │      │      │      │      │ MLflow / Redis     │
│      │      │      │      │      │      │      │ PostgreSQL         │
│      │      │      │      │      │      │      │ Alert Manager      │
├──────┴──────┴──────┴──────┴──────┴──────┴──────┴────────────────────┤
│                       Data Layer                                      │
│  yfinance │ Tiger API │ EODHD │ FRED │ WebSocket │ Parquet │ Redis   │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 Data Flow

```
T+0 pre-market:
  Data collection -> factor computation -> model inference -> signal generation

T+0 pre-market (continued):
  Signals -> Black-Litterman views -> risk model (covariance matrix) -> portfolio optimization -> target holdings

T+0 regular session:
  Live quotes -> order slicing (TWAP/VWAP) -> execution -> P&L monitoring -> circuit-breaker checks

T+0 post-market:
  Close data -> signal evaluation -> performance attribution -> model-retrain decision

Periodic:
  Weekly: factor IC evaluation + automated factor discovery
  Monthly: walk-forward retrain + model-version release
```

### 3.4 UI Mockups

#### Main dashboard layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Quant AI Trader v2                                 [Settings] [Alerts] │
├──────────────────────────────────────────────────────────────────────┤
│  Account: 20874631  │  AUM: $1,247,532  │  Daily P&L: +0.83%  │  Risk: Low │
├────────────┬────────────┬────────────┬────────────┬──────────────────┤
│  Factors   │  Models    │  Risk      │  Portfolio │  Execution       │
│  (Tab)     │  (Tab)     │  (Tab)     │  (Tab)     │  (Tab)           │
├────────────┴────────────┴────────────┴────────────┴──────────────────┤
│                                                                       │
│  ┌─ Factor Research (default) ─────────────────────────────────────┐  │
│  │ Factor search: [____________]  Type: [Technical▼]  Sort: [IC▼]  │  │
│  │ ┌───────────┬────────┬────────┬────────┬────────┬────────┐     │  │
│  │ │ Factor    │ IC mean│ IC IR  │ Latest │ Decay  │ Status │     │  │
│  │ ├───────────┼────────┼────────┼────────┼────────┼────────┤     │  │
│  │ │ mom_21d   │  0.042 │  0.68  │  0.051 │  15d   │ Active │     │  │
│  │ │ vol_ratio │ -0.038 │ -0.52  │ -0.029 │  12d   │ Decay  │     │  │
│  │ │ ...       │        │        │        │        │        │     │  │
│  │ └───────────┴────────┴────────┴────────┴────────┴────────┘     │  │
│  │                                                    112 factors │  │
│  │ [IC heatmap] [Factor corr] [Decay curve] [Strat. BT] [Auto mine]│  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─ Suggested holdings ────────────────────────────────────────────┐  │
│  │ Objective: [Max Sharpe ▼]  Constraints: name<=15% turnover<=30% │  │
│  │ ┌─────────┬────────┬────────┬────────┬────────┐                 │  │
│  │ │ Ticker  │ Curr % │ Target%│ Delta %│ Action │                 │  │
│  │ ├─────────┼────────┼────────┼────────┼────────┤                 │  │
│  │ │ AAPL    │  12.3  │  10.5  │ -1.8   │ Reduce │                 │  │
│  │ │ NVDA    │   8.2  │  12.1  │ +3.9   │ Add    │                 │  │
│  │ │ ...     │        │        │        │        │                 │  │
│  │ └─────────┴────────┴────────┴────────┴────────┘                 │  │
│  │                                                 [Rebalance]     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

#### Key pages

| Page | Core functions |
|------|----------|
| **Factor research** | Sortable / filterable factor list, single-factor IC charts, factor-correlation heatmap, factor decay curve, stratified backtest returns, automated factor-discovery progress |
| **Model center** | Per-model training status, latest evaluation metrics, SHAP feature-importance charts, predicted vs. actual scatter, model versioning |
| **Risk dashboard** | Barra factor-exposure radar, live VaR gauge, sector-concentration pie, stress-test results table, risk-budget utilization |
| **Portfolio optimization** | Efficient-frontier visualization, current vs. optimal holdings, constraint panel, optimization history |
| **Backtest analysis** | NAV curve, monthly-return heatmap, rolling Sharpe, max-drawdown annotations, Brinson attribution waterfall |
| **Execution monitor** | Order-slice progress, live vs. expected slippage, today's fills, circuit-breaker status |

### 3.5 Open Questions

| # | Question | Recommended decision |
|---|------|----------|
| Q1 | **GPU resources**: Does the current development environment have a GPU? If not, can deep-learning modules train on CPU first (small-parameter variant) and migrate to GPU in production? | Start with small-parameter CPU training to validate the pipeline; switch via a `device` config in production |
| Q2 | **Data-source priority**: yfinance has rate limits; Tiger API is paid. Should EODHD (~$30/month) be the primary source, with yfinance as backup? | P0: dual source yfinance + Tiger API; P1: evaluate EODHD cost-effectiveness |
| Q3 | **Tiger API account limits**: Does account 20874631 have programmatic order permission? Should Paper Trading be used first? | P0: validate everything in Paper Trading / backtest mode; live connectivity in P1 |
| Q4 | **Factor-count target**: Is P0 50+ or 100+? 100+ factors demand more data quality and compute. | P0: 50+ core factors first (technical 20 + fundamental 15 + alternative 10 + microstructure 5); P1: expand to 100+ |
| Q5 | **Portfolio optimizer solver**: cvxpy (free) vs. commercial (CPLEX / Gurobi)? cvxpy may be slow at 500 names. | P0: cvxpy + OSQP (open-source and fast enough); P2: evaluate commercial solvers |
| Q6 | **Database choice**: Currently SQLite; v2 needs larger scale. PostgreSQL or TimescaleDB? | Historical quotes in Parquet (columnar compression); metadata / orders / positions in PostgreSQL |
| Q7 | **Frontend framework**: Stay on Vue 3 + Vite + ECharts, or migrate to React? | Stay on Vue 3 (partial reuse of existing code); upgrade charts to ECharts 5 and add Plotly.js for statistical plots |
| Q8 | **Deployment**: Single-host Docker Compose or Kubernetes cluster? | P0: single-host Docker Compose; P2: Kubernetes |
| Q9 | **Backtest granularity**: Daily or minute-level? Minute-level is far more demanding on data volume and compute. | P0: daily backtests (fast iteration); P1: minute-level (precision validation) |
| Q10 | **Code structure**: Refactor the existing repo or create a new one? | Create a new `quant-ai-trader-v2` repo; keep v1 as reference; archive v1 after v2 is stable |

---

## 4. Suggested Milestones

| Phase | Duration | Deliverables |
|------|------|--------|
| **M1: Data + factor foundation** | 2 weeks | Multi-market data pipeline, 50+ factor computation framework, factor evaluation reports |
| **M2: AI engine** | 3 weeks | GBDT + Transformer + TFT training pipeline, walk-forward validation, MLflow integration |
| **M3: Risk + portfolio** | 2 weeks | Barra risk model, covariance estimation, Markowitz / BL optimization, constraint system |
| **M4: Backtest + execution** | 2 weeks | Event-driven backtest, slippage model, TWAP / VWAP execution, Tiger API integration |
| **M5: Frontend + integration** | 2 weeks | Vue 3 dashboard v2, system integration tests, end-to-end validation |
| **M6: Launch + monitoring** | 1 week | Docker deployment, alerting, documentation |

> **Total: ~12 weeks (3 months), 2–3 person team**

---

*Document version: v1.0 | Author: Alice (Product Manager) | Date: 2025-07-17*

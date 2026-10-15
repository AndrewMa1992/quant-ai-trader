# Architecture: Quant AI Trader v2 — Institutional-Grade AI Trading System

| Item | Content |
|------|------|
| Document version | v1.0 |
| Author | Bob (Architect) |
| Date | 2025-07-17 |
| Status | Design complete, pending review |
| Depends on PRD | `docs/PRD-v2.md` |

---

## Table of Contents

1. [Implementation Plan + Framework Selection](#1-implementation-plan--framework-selection)
2. [File List](#2-file-list)
3. [Data Structures and Interfaces](#3-data-structures-and-interfaces)
4. [Program Call Flow](#4-program-call-flow)
5. [Task List](#5-task-list)
6. [Dependency Package List](#6-dependency-package-list)
7. [Shared Knowledge](#7-shared-knowledge)
8. [Open Items](#8-open-items)

---

## 1. Implementation Plan + Framework Selection

### 1.1 Overall Architecture: Six Microservices + API Gateway

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Nginx / Traefik (reverse proxy)                    │
│                    Vue 3 SPA (Port 5180) + API (Port 8001)            │
├───────────┬──────────┬──────────┬───────────┬──────────┬──────────────┤
│  Data Svc │ Factor   │ Model    │ Model     │ Risk     │ Execution    │
│  (8011)   │ Calc     │ Train    │ Infer     │ Model    │ Engine       │
│           │ (8012)   │ (8013)   │ (8014)    │ (8015)   │ (8016)       │
├───────────┴──────────┴──────────┴───────────┴──────────┴──────────────┤
│                         Shared Infrastructure                          │
│  PostgreSQL  │  Redis (Stream+Cache+PubSub)  │  Parquet (quote store) │
│  MLflow      │  Prometheus + Grafana         │  Alert Manager          │
└──────────────────────────────────────────────────────────────────────┘
```

**Design principles**:
- Each microservice is an independent FastAPI sub-application, uniformly mounted under the API Gateway
- P0 deploys via single-host Docker Compose (all services share container orchestration); services communicate over HTTP + Redis Pub/Sub
- Services are stateless (state lives in Redis / PostgreSQL) and can scale independently

### 1.2 Core Tech Stack (locked)

| Layer | Choice | Version | Rationale |
|------|----------|------|----------|
| **Language** | Python | 3.11+ | Most complete quant ecosystem: numpy / pandas / scipy / PyTorch |
| **API framework** | FastAPI | >=0.110 | High-performance async, auto OpenAPI, native WebSocket |
| **ASGI server** | Uvicorn + Gunicorn | >=0.25 | Production deployment, multi-worker + UVLoop |
| **Deep learning** | PyTorch | >=2.2 | Flexible dynamic graphs; native Transformer / TFT |
| **GBDT** | XGBoost / LightGBM / CatBoost | latest | Pick one; GPU acceleration |
| **ML tracking** | MLflow | >=2.10 | Experiment tracking, model registry, hyperparameter logging |
| **Hyperparameter search** | Optuna | >=3.5 | Bayesian search, distributed parallelism |
| **Relational DB** | PostgreSQL + asyncpg | 16+ | Metadata, orders, positions, factor-evaluation results |
| **Cache / messaging** | Redis | 7+ | Stream (live quotes), Pub/Sub (inter-service notify), cache |
| **Columnar store** | Apache Parquet (pyarrow) | — | Compressed storage of large OHLCV histories |
| **Portfolio optimization** | cvxpy + OSQP | >=1.4 | Open-source convex solver |
| **Frontend** | Vue 3 + Vite + ECharts 5 | latest | Continues the v1 stack; team familiarity |
| **Containers** | Docker Compose | — | P0 single-host orchestration; P2 migrate to Kubernetes |
| **Logging** | Loguru | >=0.7 | Structured logs, automatic rotation |
| **Config** | Pydantic Settings + .env | >=2.7 | Type-safe configuration, environment variables |

### 1.3 Core Difficulties and Solutions

| Difficulty | Solution |
|------|----------|
| **Look-ahead bias** | Walk-forward training: time-based splits; training set contains only data before t-1; validation strictly after |
| **Ill-conditioned covariance** | Ledoit-Wolf shrinkage + exponential half-life weighting (60 days); auto-fallback to shrinkage when condition number > 1e6 |
| **Unstable GBDT GPU training** | Prefer CPU training first (GPU-ready via `device` config); parallelize with joblib |
| **Transformer exploding gradients** | Gradient clipping (1.0) + LayerNorm + warmup LR scheduler |
| **Conflicting portfolio constraints** | Hierarchical solve: first relax constraints to check feasibility, then tighten; if infeasible, return the "loosest feasible" solution |
| **Data-source rate limits** | Redis cache layer: yfinance for daily full pulls, Tiger API for live streaming, EODHD as backup |
| **Live-trading safety** | Circuit breaker (5% daily loss -> halt) + second-confirmation of orders + hard max notional per order |

### 1.4 Deployment Architecture (P0 Docker Compose)

```
docker-compose.yml:
  postgres (5432)
  redis (6379)
  api-gateway (8001)     <- FastAPI main gateway + frontend SPA
  data-service (8011)     <- data ingest / cleansing pipeline
  factor-service (8012)   <- factor computation / evaluation
  model-train-service (8013) <- offline model training jobs
  model-infer-service (8014) <- online model inference
  risk-service (8015)     <- risk-model computation
  execution-service (8016) <- order execution / Tiger API
  mlflow (5000)
```

---

## 2. File List

### 2.1 Project Root

```
quant-ai-trader/
├── .env.example                          # environment-variable template
├── .gitignore
├── .pre-commit-config.yaml
├── docker-compose.yml                    # P0 single-host deploy
├── Dockerfile.api                        # API Gateway image
├── Dockerfile.data                       # Data Service image
├── Dockerfile.factor                     # Factor Service image
├── Dockerfile.model-train                # Model Train Service image
├── Dockerfile.model-infer                # Model Infer Service image
├── Dockerfile.risk                       # Risk Service image
├── Dockerfile.execution                  # Execution Service image
├── Makefile                               # developer scripts
├── pyproject.toml                         # project metadata + tool config
├── README.md
├── _v1_archive/                           # v1 code archive
│
├── configs/
│   ├── __init__.py
│   ├── settings.py                        # global config (Pydantic Settings)
│   ├── market_universe.py                 # five-market universe (800+ stocks)
│   ├── factor_registry.py                 # factor registry (100+ factor defs)
│   └── risk_limits.py                     # risk-limit configuration
│
├── shared/                                # cross-service shared modules
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py                  # unified exception hierarchy
│   │   ├── logger.py                      # Loguru factory
│   │   ├── helpers.py                     # general utilities
│   │   └── datetime_utils.py              # trading calendar / time helpers
│   ├── database/
│   │   ├── __init__.py
│   │   ├── engine.py                      # asyncpg connection pool
│   │   ├── session.py                     # session management
│   │   └── migrations/                    # Alembic migration scripts
│   ├── models/                            # SQLAlchemy ORM models (shared)
│   │   ├── __init__.py
│   │   ├── base.py                        # base class (id, created_at, updated_at)
│   │   ├── market_data.py                 # symbol, bar, tick tables
│   │   ├── factor.py                      # factor_value, factor_eval tables
│   │   ├── model.py                       # model_version, experiment tables
│   │   ├── portfolio.py                   # position, trade, portfolio_snapshot tables
│   │   └── execution.py                   # order, execution_report tables
│   ├── redis_client.py                    # Redis connection (Stream + Pub/Sub + Cache)
│   ├── schema.py                          # cross-service Pydantic schemas
│   └── types.py                           # shared type aliases
│
├── services/                              # six microservices
│   ├── data_service/
│   │   ├── __init__.py
│   │   ├── main.py                        # FastAPI sub-app entry
│   │   ├── config.py                      # service-level config
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py                  # REST endpoints
│   │   ├── ingestion/
│   │   │   ├── __init__.py
│   │   │   ├── yfinance_client.py         # yfinance wrapper
│   │   │   ├── tiger_client.py            # Tiger OpenAPI wrapper
│   │   │   ├── eodhd_client.py            # EODHD backup data source
│   │   │   └── fred_client.py             # FRED macro data
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   ├── cleanser.py                # data cleansing (missing / anomaly)
│   │   │   ├── normalizer.py              # standardization / normalization
│   │   │   └── aggregator.py              # multi-market data fusion
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── parquet_store.py           # Parquet read / write
│   │   │   └── metadata_store.py          # PostgreSQL metadata index
│   │   ├── realtime/
│   │   │   ├── __init__.py
│   │   │   ├── ws_consumer.py             # WebSocket consumer
│   │   │   └── stream_writer.py           # Redis Stream writer
│   │   └── tasks.py                        # prefetch / scheduled tasks
│   │
│   ├── factor_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   ├── factor_base.py             # Factor abstract base class
│   │   │   └── factor_engine.py           # batch factor-computation engine
│   │   ├── factors/
│   │   │   ├── __init__.py
│   │   │   ├── technical.py               # 50+ technical factors
│   │   │   ├── fundamental.py             # 30+ fundamental factors
│   │   │   ├── alternative.py             # 20+ alternative factors
│   │   │   └── microstructure.py          # 10+ microstructure factors
│   │   ├── evaluation/
│   │   │   ├── __init__.py
│   │   │   ├── ic_analysis.py             # IC / IR analysis
│   │   │   ├── correlation.py             # factor correlation matrix
│   │   │   ├── decay.py                   # factor decay curves
│   │   │   ├── stratification.py          # stratified backtests
│   │   │   └── fama_macbeth.py            # Fama-MacBeth regression
│   │   ├── auto_discover/
│   │   │   ├── __init__.py
│   │   │   ├── genetic_programming.py     # genetic programming (P1)
│   │   │   └── candidate_pool.py          # candidate factor pool (P1)
│   │   └── neutralization/
│   │       ├── __init__.py
│   │       ├── industry_neutral.py        # industry neutralization (P1)
│   │       ├── size_neutral.py            # size neutralization (P1)
│   │       └── style_neutral.py           # style neutralization (P1)
│   │
│   ├── model_train_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── trainers/
│   │   │   ├── __init__.py
│   │   │   ├── trainer_base.py            # trainer base class
│   │   │   ├── gbdt_trainer.py            # XGBoost / LightGBM / CatBoost
│   │   │   ├── transformer_trainer.py     # Transformer trainer
│   │   │   ├── tcn_trainer.py             # TCN trainer
│   │   │   ├── tft_trainer.py             # TFT trainer
│   │   │   └── rl_trainer.py             # PPO / SAC (P1)
│   │   ├── framework/
│   │   │   ├── __init__.py
│   │   │   ├── walk_forward.py            # walk-forward framework
│   │   │   ├── timeseries_cv.py           # time-series cross-validation
│   │   │   └── early_stopping.py          # early stopping + LR scheduling
│   │   ├── hyperopt/
│   │   │   ├── __init__.py
│   │   │   └── optuna_runner.py           # Optuna hyperparameter search
│   │   ├── mlflow_manager.py              # MLflow integration
│   │   └── data_loader.py                 # training data loader
│   │
│   ├── model_infer_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── gbdt_model.py              # GBDT inference model
│   │   │   ├── transformer_model.py       # Transformer architecture
│   │   │   ├── tcn_model.py               # TCN architecture
│   │   │   ├── tft_model.py               # TFT architecture
│   │   │   └── rl_model.py               # RL policy model (P1)
│   │   ├── ensemble/
│   │   │   ├── __init__.py
│   │   │   ├── blender.py                 # static-weight blend
│   │   │   ├── bayesian_weighting.py      # dynamic Bayesian weighting (P1)
│   │   │   └── market_state.py            # HMM / GARCH market regime (P1)
│   │   ├── inference_engine.py            # inference scheduler
│   │   └── model_registry.py              # MLflow model loading
│   │
│   ├── risk_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── barra/
│   │   │   ├── __init__.py
│   │   │   ├── factor_exposure.py         # 9 style-factor exposures
│   │   │   ├── covariance.py              # Ledoit-Wolf covariance
│   │   │   └── specific_risk.py           # specific-risk estimation
│   │   ├── risk_measures/
│   │   │   ├── __init__.py
│   │   │   ├── var.py                     # VaR (parametric / historical / MC)
│   │   │   ├── cvar.py                    # CVaR / ES
│   │   │   └── drawdown.py               # max drawdown
│   │   ├── stress_test/
│   │   │   ├── __init__.py
│   │   │   ├── historical_scenarios.py    # historical extreme scenarios (P1)
│   │   │   └── custom_scenarios.py        # custom scenarios (P1)
│   │   └── attribution/
│   │       ├── __init__.py
│   │       ├── brinson.py                 # Brinson attribution (P1)
│   │       └── factor_attribution.py      # factor attribution (P1)
│   │
│   └── execution_service/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes.py
│       ├── optimizer/
│       │   ├── __init__.py
│       │   ├── markowitz.py              # mean-variance optimization
│       │   ├── black_litterman.py         # Black-Litterman
│       │   ├── risk_parity.py            # risk parity (P1)
│       │   └── constraints.py            # constraint system
│       ├── backtest/
│       │   ├── __init__.py
│       │   ├── event_engine.py            # event-driven engine
│       │   ├── events.py                  # event-type definitions
│       │   ├── broker.py                  # matching model
│       │   ├── slippage.py               # slippage model (Almgren-Chriss)
│       │   └── metrics.py                # performance metrics
│       ├── execution/
│       │   ├── __init__.py
│       │   ├── algo_base.py              # algorithm base class
│       │   ├── twap.py                   # TWAP slicing
│       │   ├── vwap.py                   # VWAP slicing
│       │   ├── pov.py                    # POV algorithm
│       │   └── tiger_executor.py         # Tiger Brokers executor
│       └── monitor/
│           ├── __init__.py
│           ├── pnl_tracker.py            # live P&L
│           └── circuit_breaker.py        # circuit breaker
│
├── api_gateway/
│   ├── __init__.py
│   ├── main.py                            # main FastAPI app (mounts all sub-routes)
│   ├── websocket_manager.py               # WebSocket connection manager
│   └── middleware/
│       ├── __init__.py
│       ├── auth.py                        # API-key authentication
│       └── logging_middleware.py          # request logging
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/
│       │   └── index.ts
│       ├── stores/
│       │   ├── index.ts                   # Pinia entry
│       │   ├── useFactorStore.ts
│       │   ├── useModelStore.ts
│       │   ├── useRiskStore.ts
│       │   ├── usePortfolioStore.ts
│       │   └── useExecutionStore.ts
│       ├── api/
│       │   ├── index.ts                   # Axios instance
│       │   ├── dataApi.ts
│       │   ├── factorApi.ts
│       │   ├── modelApi.ts
│       │   ├── riskApi.ts
│       │   └── executionApi.ts
│       ├── views/
│       │   ├── Dashboard.vue              # main dashboard
│       │   ├── FactorResearch.vue         # factor research page
│       │   ├── ModelCenter.vue            # model center
│       │   ├── RiskDashboard.vue          # risk dashboard
│       │   ├── PortfolioOptimizer.vue     # portfolio optimization
│       │   ├── BacktestAnalysis.vue       # backtest analysis
│       │   └── ExecutionMonitor.vue       # execution monitor
│       ├── components/
│       │   ├── layout/
│       │   │   ├── AppHeader.vue
│       │   │   ├── AppSidebar.vue
│       │   │   └── AppLayout.vue
│       │   ├── dashboard/
│       │   │   ├── AccountSummary.vue
│       │   │   └── MarketStatusBar.vue
│       │   ├── factor/
│       │   │   ├── FactorTable.vue
│       │   │   ├── ICRankChart.vue
│       │   │   ├── FactorCorrHeatmap.vue
│       │   │   └── DecayCurve.vue
│       │   ├── model/
│       │   │   ├── ModelStatusCard.vue
│       │   │   ├── SHAPImportance.vue
│       │   │   └── PredVsActual.vue
│       │   ├── risk/
│       │   │   ├── BarraRadar.vue
│       │   │   ├── VaRGauge.vue
│       │   │   └── SectorPie.vue
│       │   ├── portfolio/
│       │   │   ├── EfficientFrontier.vue
│       │   │   └── RebalanceTable.vue
│       │   └── execution/
│       │       ├── OrderSliceProgress.vue
│       │       └── CircuitBreakerStatus.vue
│       └── assets/
│           └── styles/
│               └── main.css               # Tailwind base + custom
│
├── scripts/
│   ├── init_db.py                          # database initialization
│   ├── ingest_historical.py               # bulk historical ingest
│   ├── run_backtest.py                     # backtest CLI
│   └── seed_factors.py                     # factor seed data
│
└── tests/
    ├── __init__.py
    ├── conftest.py                         # pytest fixtures
    ├── test_data_service/
    │   ├── test_yfinance_client.py
    │   └── test_parquet_store.py
    ├── test_factor_service/
    │   ├── test_factor_base.py
    │   ├── test_technical_factors.py
    │   └── test_ic_analysis.py
    ├── test_model_service/
    │   ├── test_walk_forward.py
    │   └── test_transformer.py
    ├── test_risk_service/
    │   ├── test_covariance.py
    │   └── test_var.py
    └── test_execution_service/
        ├── test_markowitz.py
        └── test_backtest_engine.py
```

---

## 3. Data Structures and Interfaces

### 3.1 Core Data Models (SQLAlchemy ORM)

```mermaid
classDiagram
    class BaseModel {
        +UUID id
        +datetime created_at
        +datetime updated_at
    }

    class Symbol {
        +str ticker
        +str name
        +str market
        +str currency
        +str sector
        +str industry
        +bool active
    }

    class DailyBar {
        +str ticker
        +date trade_date
        +float open
        +float high
        +float low
        +float close
        +int volume
        +float adj_close
    }

    class MinuteBar {
        +str ticker
        +datetime timestamp
        +float open
        +float high
        +float low
        +float close
        +int volume
    }

    class FactorValue {
        +str ticker
        +date calc_date
        +str factor_name
        +float value
        +str category
    }

    class FactorEvaluation {
        +str factor_name
        +date eval_date
        +float ic_mean
        +float ic_std
        +float ir
        +str status
    }

    class ModelVersion {
        +str model_name
        +str version
        +str mlflow_run_id
        +str artifact_path
        +dict hyperparams
        +dict metrics
        +str status
    }

    class Experiment {
        +str name
        +str model_type
        +dict config
        +str status
    }

    class Position {
        +str ticker
        +float shares
        +float avg_cost
        +float market_value
        +float unrealized_pnl
    }

    class Trade {
        +str ticker
        +str side
        +float quantity
        +float price
        +float commission
        +datetime executed_at
        +str order_type
    }

    class Order {
        +str ticker
        +str side
        +float quantity
        +float limit_price
        +str algo_type
        +str status
        +float filled_qty
        +float avg_fill_price
    }

    class PortfolioSnapshot {
        +datetime timestamp
        +float total_value
        +float cash
        +float positions_value
        +float daily_pnl
        +float var_95
    }

    BaseModel <|-- Symbol
    BaseModel <|-- DailyBar
    BaseModel <|-- FactorValue
    BaseModel <|-- FactorEvaluation
    BaseModel <|-- ModelVersion
    BaseModel <|-- Experiment
    BaseModel <|-- Position
    BaseModel <|-- Trade
    BaseModel <|-- Order
    BaseModel <|-- PortfolioSnapshot
    DailyBar -- Symbol : "ticker"
    FactorValue -- Symbol : "ticker"
    Position -- Symbol : "ticker"
    Trade -- Order : "fills"
```

### 3.2 Service Core Class Diagram

```mermaid
classDiagram
    class DataService {
        +YFinanceClient yfinance
        +TigerClient tiger
        +ParquetStore store
        +StreamWriter stream
        +fetch_historical(tickers, start, end) DataFrame
        +subscribe_realtime(tickers) None
        +get_daily_bars(ticker, start, end) DataFrame
    }

    class FactorEngine {
        +List~FactorBase~ factors
        +FactorEvaluator evaluator
        +compute_all(date) Dict
        +compute_single(factor_name, ticker, date) float
        +evaluate(factor_name) FactorReport
        +get_factor_matrix(date) DataFrame
    }

    class FactorBase {
        <<abstract>>
        +str name
        +str category
        +int lookback
        +compute(ohlcv, fundamentals) Series
        +validate() bool
    }

    class TechnicalFactor {
        +compute(ohlcv) Series
    }

    class FundamentalFactor {
        +compute(ohlcv, fundamentals) Series
    }

    class AlternativeFactor {
        +compute(ohlcv, alt_data) Series
    }

    class MicrostructureFactor {
        +compute(tick_data) Series
    }

    class ModelTrainer {
        +WalkForwardFramework wf
        +OptunaRunner optuna
        +MLflowManager mlflow
        +train(model_type, data, config) ModelVersion
        +hyperopt(model_type, data, n_trials) BestParams
        +evaluate(model, test_data) Metrics
    }

    class WalkForwardFramework {
        +int n_splits
        +int train_window
        +int validation_window
        +run(model_factory, data, config) Results
    }

    class InferenceEngine {
        +ModelRegistry registry
        +EnsembleBlender blender
        +MarketStateDetector state_detector
        +predict(ticker, features) Prediction
        +batch_predict(tickers, factor_data) DataFrame
        +get_signals(date) SignalMatrix
    }

    class ModelRegistry {
        +MLflowClient mlflow_client
        +load_model(model_name, version) Model
        +get_latest(model_name) ModelVersion
        +list_models() List
    }

    class EnsembleBlender {
        +Dict weights
        +blend(predictions) Signal
        +update_weights(performance) None
    }

    class RiskModel {
        +BarraExposureCalculator barra
        +CovarianceEstimator cov
        +VaRCalculator var_calc
        +compute_exposures(holdings) DataFrame
        +compute_covariance(returns) ndarray
        +compute_var(holdings, confidence) float
        +compute_cvar(holdings, confidence) float
    }

    class BarraExposureCalculator {
        +compute_beta(returns, benchmark) float
        +compute_size(log_mcap) float
        +compute_value(bp, ep, cfp) float
        +compute_momentum(ret_12m1m) float
        +compute_quality(roe, de) float
        +compute_volatility(beta, sigma) float
        +compute_growth(egro, sgro) float
        +compute_leverage(dte, dte_ma) float
        +compute_liquidity(turnover) float
    }

    class CovarianceEstimator {
        +ledoit_wolf(returns) ndarray
        +ewma(returns, halflife) ndarray
        +shrinkage_intensity(cov_sample) float
    }

    class VaRCalculator {
        +parametric(returns, confidence) float
        +historical(returns, confidence) float
        +monte_carlo(returns, confidence, n_sim) float
    }

    class PortfolioOptimizer {
        +OptimizerConfig config
        +ConstraintSystem constraints
        +optimize(returns, cov, signals) Holdings
        +black_litterman(prior, views, confidence) Posterior
        +efficient_frontier(returns, cov, points) Frontier
    }

    class ConstraintSystem {
        +List~Constraint~ constraints
        +validate(weights) bool
        +to_cvxpy(weights_var) List
    }

    class BacktestEngine {
        +EventEngine event_engine
        +Broker broker
        +SlippageModel slippage
        +MetricsCalculator metrics
        +run(strategy, data, config) BacktestResult
        +report(result) Report
    }

    class ExecutionEngine {
        +AlgoBase twap_algo
        +AlgoBase vwap_algo
        +TigerExecutor tiger
        +CircuitBreaker breaker
        +execute_order(order, algo) ExecutionReport
        +cancel_order(order_id) bool
        +get_status() ExecutionStatus
    }

    class CircuitBreaker {
        +float daily_loss_limit
        +float current_daily_pnl
        +check() bool
        +trip(reason) None
        +reset() None
    }

    FactorBase <|-- TechnicalFactor
    FactorBase <|-- FundamentalFactor
    FactorBase <|-- AlternativeFactor
    FactorBase <|-- MicrostructureFactor
    FactorEngine o-- FactorBase
    ModelTrainer o-- WalkForwardFramework
    InferenceEngine o-- ModelRegistry
    InferenceEngine o-- EnsembleBlender
    RiskModel o-- BarraExposureCalculator
    RiskModel o-- CovarianceEstimator
    RiskModel o-- VaRCalculator
    PortfolioOptimizer o-- ConstraintSystem
    ExecutionEngine o-- CircuitBreaker
```

### 3.3 REST API Endpoint Summary

#### API Gateway (Port 8001)

| Method | Path | Service | Description |
|--------|------|---------|-------------|
| `GET` | `/health` | Gateway | Health check |
| `WS` | `/ws` | Gateway | Live-data WebSocket |
| `GET` | `/api/v2/data/symbols` | Data | Universe list |
| `GET` | `/api/v2/data/bars/{ticker}` | Data | Historical bars |
| `GET` | `/api/v2/data/bars/{ticker}/minute` | Data | Minute bars |
| `GET` | `/api/v2/data/realtime/{ticker}` | Data | Live quote |
| `POST` | `/api/v2/data/ingest` | Data | Trigger data ingest |
| `GET` | `/api/v2/factors/list` | Factor | Factor list + metrics |
| `GET` | `/api/v2/factors/{name}/analysis` | Factor | Single-factor analysis |
| `GET` | `/api/v2/factors/matrix` | Factor | Factor-value matrix |
| `POST` | `/api/v2/factors/compute` | Factor | Compute today's factors |
| `GET` | `/api/v2/factors/correlation` | Factor | Factor correlation matrix |
| `GET` | `/api/v2/factors/decay/{name}` | Factor | Factor decay curve |
| `POST` | `/api/v2/models/train` | Train | Start training |
| `GET` | `/api/v2/models/train/status/{run_id}` | Train | Training status |
| `GET` | `/api/v2/models/versions` | Train/Infer | Model-version list |
| `POST` | `/api/v2/models/hyperopt` | Train | Start hyperparameter search |
| `POST` | `/api/v2/models/predict` | Infer | Batch inference |
| `GET` | `/api/v2/models/signals` | Infer | Today's signals |
| `GET` | `/api/v2/models/features/{ticker}` | Infer | SHAP feature importance |
| `GET` | `/api/v2/risk/exposures` | Risk | Barra factor exposures |
| `GET` | `/api/v2/risk/var` | Risk | VaR / CVaR metrics |
| `GET` | `/api/v2/risk/covariance` | Risk | Covariance matrix |
| `POST` | `/api/v2/risk/stress-test` | Risk | Stress test (P1) |
| `GET` | `/api/v2/risk/attribution` | Risk | Performance attribution (P1) |
| `POST` | `/api/v2/portfolio/optimize` | Exec | Portfolio optimization |
| `GET` | `/api/v2/portfolio/frontier` | Exec | Efficient frontier |
| `GET` | `/api/v2/portfolio/holdings` | Exec | Current holdings |
| `POST` | `/api/v2/portfolio/rebalance` | Exec | Execute rebalance |
| `POST` | `/api/v2/backtest/run` | Exec | Run backtest |
| `GET` | `/api/v2/backtest/result/{run_id}` | Exec | Backtest result |
| `GET` | `/api/v2/backtest/report/{run_id}` | Exec | Backtest report |
| `POST` | `/api/v2/execution/order` | Exec | Submit order |
| `GET` | `/api/v2/execution/orders` | Exec | Order list |
| `GET` | `/api/v2/execution/pnl` | Exec | Live P&L |
| `GET` | `/api/v2/execution/circuit-breaker` | Exec | Circuit-breaker status |

### 3.4 Unified Response Format

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "timestamp": "2025-07-17T10:30:00Z",
  "request_id": "uuid-v4"
}
```

Error codes:
- `0` = success
- `1001` = validation error
- `2001` = data source unavailable
- `3001` = model not ready
- `4001` = risk check failed
- `4002` = circuit breaker tripped
- `5001` = execution rejected
- `9000` = internal error

---

## 4. Program Call Flow

### 4.1 Training Flow (Walk-Forward + MLflow)

```mermaid
sequenceDiagram
    participant User as User / Frontend
    participant GW as API Gateway
    participant Train as Model Train Service
    participant Data as Data Service
    participant Factor as Factor Service
    participant MLflow as MLflow Server
    participant PG as PostgreSQL
    participant Disk as Parquet Store

    User->>GW: POST /api/v2/models/train {model_type, config}
    GW->>Train: Forward training request
    Train->>MLflow: create_experiment(name)
    MLflow-->>Train: experiment_id
    
    Train->>Data: GET /api/v2/data/bars?tickers=ALL&period=2y
    Data->>Disk: read parquet files
    Disk-->>Data: OHLCV DataFrame
    Data-->>Train: OHLCV data
    
    Train->>Factor: POST /api/v2/factors/compute {start_date, end_date}
    Factor->>Factor: Batch-compute 100+ factors
    Factor-->>Train: factor_matrix
    
    loop Walk-Forward Split (k=3)
        Train->>Train: Split train / val time windows
        Train->>Train: Feature standardize (fit on train)
        Train->>MLflow: start_run()
        
        Train->>Train: model.fit(X_train, y_train)
        Train->>Train: pred = model.predict(X_val)
        Train->>Train: Compute IC / Sharpe / max_dd
        
        Train->>MLflow: log_params(config)
        Train->>MLflow: log_metrics({ic, sharpe, ...})
        Train->>MLflow: log_model(model_artifact)
        Train->>MLflow: end_run()
    end
    
    Train->>PG: INSERT model_version (version, path, metrics)
    Train->>MLflow: register_model(best_model)
    Train-->>GW: {status: "completed", run_id, metrics}
    GW-->>User: Training complete + evaluation metrics
```

### 4.2 Inference + Trading Flow (T+0 Pre-Market / Regular Session)

```mermaid
sequenceDiagram
    participant Cron as Scheduler
    participant GW as API Gateway
    participant Data as Data Service
    participant Factor as Factor Service
    participant Infer as Model Infer Service
    participant Risk as Risk Service
    participant Exec as Execution Service
    participant Tiger as Tiger OpenAPI
    participant Redis as Redis Stream
    participant PG as PostgreSQL

    Note over Cron,PG: ===== T+0 pre-market (08:00) =====
    Cron->>GW: POST /api/v2/data/ingest
    GW->>Data: Trigger full-universe ingest
    Data->>Data: yfinance batch OHLCV pull
    Data->>Disk: Write Parquet
    Data->>PG: Update metadata index

    Cron->>GW: POST /api/v2/factors/compute
    GW->>Factor: Compute today's factors
    Factor->>Data: Fetch latest quotes
    Factor->>Factor: Vectorized batch compute of 100+ factors
    Factor->>PG: Write factor_values
    Factor-->>GW: Factor computation complete

    Cron->>GW: POST /api/v2/models/predict
    GW->>Infer: Batch inference
    Infer->>MLflow: load latest model
    Infer->>Factor: GET /api/v2/factors/matrix
    Infer->>Infer: ensemble.predict(factor_matrix)
    Infer->>PG: Write signals
    Infer-->>GW: {signals: [...], timestamp}

    GW->>Risk: GET /api/v2/risk/covariance
    Risk->>Risk: Ledoit-Wolf covariance matrix

    GW->>Exec: POST /api/v2/portfolio/optimize
    Exec->>Infer: Fetch signals (as BL views)
    Exec->>Risk: Fetch covariance matrix
    Exec->>Exec: Black-Litterman + Markowitz optimize
    Exec-->>GW: {target_holdings: [...], trades: [...]}

    Note over Cron,PG: ===== T+0 regular session (09:30-16:00) =====
    Tiger->>Data: WebSocket live quote push
    Data->>Redis: XADD stream:market_ticks
    Redis-->>GW: Pub/Sub broadcast market data
    GW->>GW: WebSocket push to frontend

    loop Every 10 minutes
        Exec->>Exec: TWAP / VWAP order-slice execution
        Exec->>Tiger: Submit child order
        Tiger-->>Exec: Fill confirmation
        
        Exec->>Risk: Live risk check
        Risk->>Risk: Check circuit-breaker conditions
        Risk-->>Exec: {passed: true/false}
        
        alt Circuit breaker tripped
            Exec->>Exec: Pause trading + alert
            Exec->>PG: Record circuit-breaker event
        end
        
        Exec->>PG: Update positions / orders
        Exec->>Redis: PUBLISH trade_updates
    end

    Note over Cron,PG: ===== T+0 post-market (16:30) =====
    Cron->>Exec: POST /api/v2/backtest/report
    Exec->>Exec: Compute today's performance metrics
    Exec->>PG: Write portfolio_snapshot
```

### 4.3 Real-Time Data Flow (WebSocket + Redis Stream)

```mermaid
sequenceDiagram
    participant Tiger as Tiger WS API
    participant Data as Data Service
    participant Redis as Redis
    participant GW as API Gateway
    participant FE as Vue 3 Frontend
    participant PG as PostgreSQL

    Data->>Tiger: Subscribe live quotes (800+ tickers)
    
    loop Live push
        Tiger->>Data: WebSocket tick data
        Data->>Data: Normalize format + multi-market timezone conversion
        
        par Write Redis Stream
            Data->>Redis: XADD stream:market_ticks * ticker price volume
        and Update live cache
            Data->>Redis: SET ticker:{symbol} {price, change, ...}
        and Broadcast to Gateway
            Data->>GW: HTTP POST /api/push/tick
        end
        
        GW->>GW: Check circuit-breaker status
        GW->>FE: WebSocket push {type: "market_tick", data}
        FE->>FE: Update charts (ECharts 5)
        
        alt Every 60 seconds
            Data->>PG: Bulk-insert tick records (async)
        end
    end
    
    Note over Data,PG: Post-market (16:00+)
    Data->>Data: Stop live stream
    Data->>PG: Archive today's ticks -> daily bars
    Data->>Disk: Write Parquet (date partitioned)
```

---

## 5. Task List

> **HARD LIMITS**: At most 5 tasks. Each task must include at least 3 related files. Group by functional module, not by individual file.

| Task ID | Task Name | Source Files | Dependencies | Priority |
|---------|-----------|-------------|--------------|----------|
| **T01** | **Project infrastructure + config + shared modules** | `pyproject.toml`, `docker-compose.yml`, `Dockerfile.*`x7, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, `Makefile`, `configs/__init__.py`, `configs/settings.py`, `configs/market_universe.py`, `configs/factor_registry.py`, `configs/risk_limits.py`, `shared/__init__.py`, `shared/core/__init__.py`, `shared/core/exceptions.py`, `shared/core/logger.py`, `shared/core/helpers.py`, `shared/core/datetime_utils.py`, `shared/database/__init__.py`, `shared/database/engine.py`, `shared/database/session.py`, `shared/database/migrations/`, `shared/models/__init__.py`, `shared/models/base.py`, `shared/models/market_data.py`, `shared/models/factor.py`, `shared/models/model.py`, `shared/models/portfolio.py`, `shared/models/execution.py`, `shared/redis_client.py`, `shared/schema.py`, `shared/types.py`, `api_gateway/__init__.py`, `api_gateway/main.py`, `api_gateway/websocket_manager.py`, `api_gateway/middleware/__init__.py`, `api_gateway/middleware/auth.py`, `api_gateway/middleware/logging_middleware.py`, `scripts/init_db.py`, `tests/conftest.py`, `frontend/index.html`, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`, `frontend/src/main.ts`, `frontend/src/App.vue`, `frontend/src/router/index.ts`, `frontend/src/api/index.ts`, `frontend/src/assets/styles/main.css` | — (no dependencies) | P0 |
| **T02** | **Data service + factor service (end-to-end data pipeline)** | `services/data_service/__init__.py`, `services/data_service/main.py`, `services/data_service/config.py`, `services/data_service/api/__init__.py`, `services/data_service/api/routes.py`, `services/data_service/ingestion/__init__.py`, `services/data_service/ingestion/yfinance_client.py`, `services/data_service/ingestion/tiger_client.py`, `services/data_service/ingestion/eodhd_client.py`, `services/data_service/ingestion/fred_client.py`, `services/data_service/pipeline/__init__.py`, `services/data_service/pipeline/cleanser.py`, `services/data_service/pipeline/normalizer.py`, `services/data_service/pipeline/aggregator.py`, `services/data_service/storage/__init__.py`, `services/data_service/storage/parquet_store.py`, `services/data_service/storage/metadata_store.py`, `services/data_service/realtime/__init__.py`, `services/data_service/realtime/ws_consumer.py`, `services/data_service/realtime/stream_writer.py`, `services/data_service/tasks.py`, `services/factor_service/__init__.py`, `services/factor_service/main.py`, `services/factor_service/config.py`, `services/factor_service/api/__init__.py`, `services/factor_service/api/routes.py`, `services/factor_service/engine/__init__.py`, `services/factor_service/engine/factor_base.py`, `services/factor_service/engine/factor_engine.py`, `services/factor_service/factors/__init__.py`, `services/factor_service/factors/technical.py`, `services/factor_service/factors/fundamental.py`, `services/factor_service/factors/alternative.py`, `services/factor_service/factors/microstructure.py`, `services/factor_service/evaluation/__init__.py`, `services/factor_service/evaluation/ic_analysis.py`, `services/factor_service/evaluation/correlation.py`, `services/factor_service/evaluation/decay.py`, `services/factor_service/evaluation/stratification.py`, `services/factor_service/evaluation/fama_macbeth.py`, `scripts/seed_factors.py`, `scripts/ingest_historical.py`, `tests/test_data_service/`, `tests/test_factor_service/` | T01 | P0 |
| **T03** | **Model train + model infer services (end-to-end AI engine)** | `services/model_train_service/__init__.py`, `services/model_train_service/main.py`, `services/model_train_service/config.py`, `services/model_train_service/api/__init__.py`, `services/model_train_service/api/routes.py`, `services/model_train_service/trainers/__init__.py`, `services/model_train_service/trainers/trainer_base.py`, `services/model_train_service/trainers/gbdt_trainer.py`, `services/model_train_service/trainers/transformer_trainer.py`, `services/model_train_service/trainers/tcn_trainer.py`, `services/model_train_service/trainers/tft_trainer.py`, `services/model_train_service/trainers/rl_trainer.py`, `services/model_train_service/framework/__init__.py`, `services/model_train_service/framework/walk_forward.py`, `services/model_train_service/framework/timeseries_cv.py`, `services/model_train_service/framework/early_stopping.py`, `services/model_train_service/hyperopt/__init__.py`, `services/model_train_service/hyperopt/optuna_runner.py`, `services/model_train_service/mlflow_manager.py`, `services/model_train_service/data_loader.py`, `services/model_infer_service/__init__.py`, `services/model_infer_service/main.py`, `services/model_infer_service/config.py`, `services/model_infer_service/api/__init__.py`, `services/model_infer_service/api/routes.py`, `services/model_infer_service/models/__init__.py`, `services/model_infer_service/models/gbdt_model.py`, `services/model_infer_service/models/transformer_model.py`, `services/model_infer_service/models/tcn_model.py`, `services/model_infer_service/models/tft_model.py`, `services/model_infer_service/models/rl_model.py`, `services/model_infer_service/ensemble/__init__.py`, `services/model_infer_service/ensemble/blender.py`, `services/model_infer_service/ensemble/bayesian_weighting.py`, `services/model_infer_service/ensemble/market_state.py`, `services/model_infer_service/inference_engine.py`, `services/model_infer_service/model_registry.py`, `tests/test_model_service/` | T01, T02 (needs factor-computed factor data) | P0 |
| **T04** | **Risk service + execution service (risk + backtest + portfolio opt + execution)** | `services/risk_service/__init__.py`, `services/risk_service/main.py`, `services/risk_service/config.py`, `services/risk_service/api/__init__.py`, `services/risk_service/api/routes.py`, `services/risk_service/barra/__init__.py`, `services/risk_service/barra/factor_exposure.py`, `services/risk_service/barra/covariance.py`, `services/risk_service/barra/specific_risk.py`, `services/risk_service/risk_measures/__init__.py`, `services/risk_service/risk_measures/var.py`, `services/risk_service/risk_measures/cvar.py`, `services/risk_service/risk_measures/drawdown.py`, `services/risk_service/stress_test/__init__.py`, `services/risk_service/stress_test/historical_scenarios.py`, `services/risk_service/stress_test/custom_scenarios.py`, `services/risk_service/attribution/__init__.py`, `services/risk_service/attribution/brinson.py`, `services/risk_service/attribution/factor_attribution.py`, `services/execution_service/__init__.py`, `services/execution_service/main.py`, `services/execution_service/config.py`, `services/execution_service/api/__init__.py`, `services/execution_service/api/routes.py`, `services/execution_service/optimizer/__init__.py`, `services/execution_service/optimizer/markowitz.py`, `services/execution_service/optimizer/black_litterman.py`, `services/execution_service/optimizer/risk_parity.py`, `services/execution_service/optimizer/constraints.py`, `services/execution_service/backtest/__init__.py`, `services/execution_service/backtest/event_engine.py`, `services/execution_service/backtest/events.py`, `services/execution_service/backtest/broker.py`, `services/execution_service/backtest/slippage.py`, `services/execution_service/backtest/metrics.py`, `services/execution_service/execution/__init__.py`, `services/execution_service/execution/algo_base.py`, `services/execution_service/execution/twap.py`, `services/execution_service/execution/vwap.py`, `services/execution_service/execution/pov.py`, `services/execution_service/execution/tiger_executor.py`, `services/execution_service/monitor/__init__.py`, `services/execution_service/monitor/pnl_tracker.py`, `services/execution_service/monitor/circuit_breaker.py`, `scripts/run_backtest.py`, `tests/test_risk_service/`, `tests/test_execution_service/` | T01, T02 (needs data and factors), T03 (needs inference signals) | P0 |
| **T05** | **Frontend SPA + system integration + alerting + joint debug** | `frontend/src/stores/index.ts`, `frontend/src/stores/useFactorStore.ts`, `frontend/src/stores/useModelStore.ts`, `frontend/src/stores/useRiskStore.ts`, `frontend/src/stores/usePortfolioStore.ts`, `frontend/src/stores/useExecutionStore.ts`, `frontend/src/api/dataApi.ts`, `frontend/src/api/factorApi.ts`, `frontend/src/api/modelApi.ts`, `frontend/src/api/riskApi.ts`, `frontend/src/api/executionApi.ts`, `frontend/src/views/Dashboard.vue`, `frontend/src/views/FactorResearch.vue`, `frontend/src/views/ModelCenter.vue`, `frontend/src/views/RiskDashboard.vue`, `frontend/src/views/PortfolioOptimizer.vue`, `frontend/src/views/BacktestAnalysis.vue`, `frontend/src/views/ExecutionMonitor.vue`, `frontend/src/components/layout/AppHeader.vue`, `frontend/src/components/layout/AppSidebar.vue`, `frontend/src/components/layout/AppLayout.vue`, `frontend/src/components/dashboard/AccountSummary.vue`, `frontend/src/components/dashboard/MarketStatusBar.vue`, `frontend/src/components/factor/FactorTable.vue`, `frontend/src/components/factor/ICRankChart.vue`, `frontend/src/components/factor/FactorCorrHeatmap.vue`, `frontend/src/components/factor/DecayCurve.vue`, `frontend/src/components/model/ModelStatusCard.vue`, `frontend/src/components/model/SHAPImportance.vue`, `frontend/src/components/model/PredVsActual.vue`, `frontend/src/components/risk/BarraRadar.vue`, `frontend/src/components/risk/VaRGauge.vue`, `frontend/src/components/risk/SectorPie.vue`, `frontend/src/components/portfolio/EfficientFrontier.vue`, `frontend/src/components/portfolio/RebalanceTable.vue`, `frontend/src/components/execution/OrderSliceProgress.vue`, `frontend/src/components/execution/CircuitBreakerStatus.vue` | T01, T02, T03, T04 (all backend services ready) | P0 |

### 5.1 Task Dependency Graph

```mermaid
graph TD
    T01["T01: Project infrastructure + config + shared modules<br/>(~50 files)"]
    T02["T02: Data service + factor service<br/>(~43 files)"]
    T03["T03: Model train + model infer services<br/>(~38 files)"]
    T04["T04: Risk service + execution service<br/>(~47 files)"]
    T05["T05: Frontend SPA + system integration + joint debug<br/>(~37 files)"]

    T01 --> T02
    T01 --> T03
    T01 --> T04
    T02 --> T03
    T02 --> T04
    T03 --> T04
    T02 --> T05
    T03 --> T05
    T04 --> T05
```

---

## 6. Dependency Package List

### 6.1 Core Dependencies (`pyproject.toml` dependencies)

```
# ============================================================
# Quant AI Trader v2 - Core Dependencies
# ============================================================

# --- API Framework ---
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
gunicorn>=21.2.0
websockets>=12.0

# --- Data Processing ---
numpy>=1.26.0
pandas>=2.2.0
scipy>=1.12.0
pyarrow>=15.0.0          # Parquet read/write

# --- Database ---
asyncpg>=0.29.0
sqlalchemy[asyncio]>=2.0.25
alembic>=1.13.0
psycopg2-binary>=2.9.9   # Alembic migrations

# --- Cache / Message ---
redis[hiredis]>=5.0.1
aioredis>=2.0.1

# --- Machine Learning ---
scikit-learn>=1.4.0
xgboost>=2.0.3
lightgbm>=4.3.0
catboost>=1.2.3

# --- Deep Learning ---
torch>=2.2.0

# --- Hyperparameter Search ---
optuna>=3.5.0

# --- ML Tracking ---
mlflow>=2.10.0

# --- Portfolio Optimization ---
cvxpy>=1.4.1
osqp>=0.6.5

# --- Data Acquisition ---
yfinance>=0.2.36
tigeropen>=3.5.8

# --- Factor Calculations ---
ta-lib>=0.4.28           # Low-level TA indicators (C library)
ta>=0.10.2               # Pure Python TA (backup)
gplearn>=0.4.1           # Genetic programming (P1 auto-discovery)
statsmodels>=0.14.1      # Fama-MacBeth, HMM

# --- Utilities ---
pydantic>=2.6.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.1
loguru>=0.7.2
tqdm>=4.66.0
httpx>=0.26.0            # Async HTTP client
python-dateutil>=2.8.2
pytz>=2024.1
orjson>=3.9.0            # Fast JSON serialization

# --- Alerting ---
slack-sdk>=3.27.0
# wechat-work-bot (WeChat Work)

# --- Visualization (Backend) ---
matplotlib>=3.8.0
seaborn>=0.13.0

# --- Testing ---
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0

# --- Code Quality ---
black>=24.0.0
ruff>=0.2.0
mypy>=1.8.0
```

### 6.2 Frontend Dependencies (`frontend/package.json`)

```json
{
  "dependencies": {
    "vue": "^3.4",
    "vue-router": "^4.3",
    "pinia": "^2.1",
    "axios": "^1.6",
    "echarts": "^5.5",
    "vue-echarts": "^6.6",
    "dayjs": "^1.11",
    "@vueuse/core": "^10.7"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0",
    "vite": "^5.1",
    "typescript": "^5.3",
    "tailwindcss": "^3.4",
    "postcss": "^8.4",
    "autoprefixer": "^10.4",
    "@types/node": "^20.11",
    "vue-tsc": "^1.8"
  }
}
```

---

## 7. Shared Knowledge

### 7.1 Naming Conventions

| Layer | Convention | Example |
|------|------|------|
| **Python files** | snake_case | `factor_engine.py`, `walk_forward.py` |
| **Python classes** | PascalCase | `FactorEngine`, `WalkForwardFramework` |
| **Python functions / methods** | snake_case | `compute_all()`, `get_historical_data()` |
| **Python constants** | UPPER_SNAKE | `FACTOR_CATEGORIES`, `MAX_POSITION_SIZE` |
| **Database table names** | snake_case plural | `daily_bars`, `factor_values`, `orders` |
| **Database column names** | snake_case | `trade_date`, `factor_name`, `avg_cost` |
| **API paths** | kebab-case | `/api/v2/factors/correlation` |
| **TypeScript files** | camelCase (special) -> `use` prefix for stores | `useFactorStore.ts`, `dataApi.ts` |
| **Vue components** | PascalCase | `FactorTable.vue`, `VaRGauge.vue` |
| **Docker images** | lowercase-hyphen | `quant-factor-service` |
| **Git branches** | `feature/`, `fix/`, `chore/` prefix | `feature/walk-forward-trainer` |

### 7.2 Configuration Management

- All configuration is managed via Pydantic `BaseSettings` in `configs/settings.py`
- Environment-variable prefix: `QAT_` (Quant AI Trader)
- `.env` lives at the project root and is not committed to Git
- Each service has its own `config.py` inheriting the base class and overriding service-specific settings
- Secrets (`TIGER_PRIVATE_KEY`, `DB_PASSWORD`) must be injected via environment variables

```python
# settings.py example
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QAT_", env_file=".env")

    # Database
    POSTGRES_URL: str = "postgresql+asyncpg://qat:qat@localhost:5432/qat_v2"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MLflow
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"

    # GPU
    DEVICE: str = "cpu"  # "cuda:0" on GPU machines

    # Alerts
    SLACK_WEBHOOK_URL: str = ""
    WECHAT_WEBHOOK_URL: str = ""
    SMTP_HOST: str = ""
    ALERT_EMAIL: str = ""
```

### 7.3 Exception Handling

```python
# shared/core/exceptions.py
class QuantAIException(Exception):
    """Base class for all custom exceptions."""
    def __init__(self, message: str, code: int = 9000, detail: dict = None):
        self.message = message
        self.code = code
        self.detail = detail or {}

class DataSourceUnavailable(QuantAIException):
    """Data source unavailable (code: 2001)."""

class ModelNotReady(QuantAIException):
    """Model not trained / not loaded (code: 3001)."""

class RiskCheckFailed(QuantAIException):
    """Risk check failed (code: 4001)."""

class CircuitBreakerTripped(QuantAIException):
    """Circuit breaker already tripped (code: 4002)."""

class ExecutionRejected(QuantAIException):
    """Order execution rejected (code: 5001)."""
```

### 7.4 Logging Conventions

- All services use `loguru` for unified logging
- Format: `{time:ISO} | {level: <8} | {service}:{module}:{line} | {message}`
- Levels: DEBUG < INFO < WARNING < ERROR < CRITICAL
- INFO: key business events (data pull complete, factor computation complete, model loaded, order filled)
- WARNING: recoverable exceptions (data-source retry, cache miss, constraint relaxation)
- ERROR: exceptions that need attention (data-source failure, model-load failure, order rejected)
- Log files: `logs/{service}/{date}.log`, automatic rotation (100 MB / file, retain 30 days)
- Production: INFO; development: DEBUG

### 7.5 Data Format Conventions

- All timestamps: ISO 8601 UTC (`2025-07-17T10:30:00Z`)
- Database date columns: `date` type (no timezone)
- Tickers: uppercase; HK append `.HK`, Singapore `.SI`, Australia `.AX`, New Zealand `.NZ`
- Currency: store all values in USD; multi-currency conversion uses the FX table in `configs/settings.py`
- Parquet partitioning: `market={market}/year={YYYY}/month={MM}/` (Hive-style)
- Factor values: float64; NaN means missing (automatic forward fill)
- Missing-value sentinel: -99999 for specially marked missing values

### 7.6 Numeric Precision and Types

- Price: `Decimal(10, 4)` in PostgreSQL, `float64` in memory
- Quantity: `int` (whole shares)
- Weights: `float64`, range [0, 1]
- Returns: `float64`, decimal form (0.01 = 1%)
- Covariance matrix: `float64` ndarray
- GPU tensors: `float32` (performance first)

### 7.7 API Design Conventions

- All responses use a unified format: `{code, message, data, timestamp, request_id}`
- List responses are paginated: `{code, data: {items, total, page, page_size}, ...}`
- Time-range queries: `start_date`, `end_date` parameters, ISO 8601 date format
- Batch endpoints: POST body with `tickers: list[str]`
- Long-running operations (train / backtest): return `run_id`; client polls status

### 7.8 Security Conventions

- Tiger API private key: inject via environment variable only; never write to any file
- API-key auth: `X-API-Key` header, verified in `api_gateway/middleware/auth.py`
- Database passwords: via Docker secrets or environment variables
- All external API calls: timeout set (default 30s)
- Production: CORS allow-list, HTTPS only

---

## 8. Open Items

| # | Item | Scope | Recommended decision |
|---|------|----------|----------|
| **Q1** | **Tiger API programmatic-order permission**: Does account 20874631 have programmatic trading rights? Is a signed agreement required first? | Execution Service | P0: validate the order pipeline in Tiger Paper Trading first; the live account is used only for quotes + position queries; orders require human confirmation |
| **Q2** | **yfinance rate-limit handling**: A full 800+ name daily pull may trigger Yahoo throttling | Data Service | Implement exponential backoff + batched pulls (50 names per batch, 2s interval); reduce duplicate requests via daily-data cache hits |
| **Q3** | **TA-Lib install compatibility**: TA-Lib requires compiling C extensions; Windows / Mac installs are painful | Factor Service | Pre-compile in the Docker image; Windows development uses `ta` (pure Python) as fallback |
| **Q4** | **PostgreSQL vs. SQLite transition**: The PRD notes P0 might keep SQLite | Database | P0: use PostgreSQL directly (one Docker line to start); zero extra cost and avoids a later migration |
| **Q5** | **Transformer d_model target**: PRD requires d_model >= 512, but P0 CPU training may be very slow | Model Train Service | Provide small / large configs: small (d_model=128) for fast validation and CPU training; large (d_model=512) for GPU production training |
| **Q6** | **Does the frontend need Plotly.js?**: PRD Q7 mentioned adding Plotly.js for statistical plots | Frontend | P0: ECharts 5 only (covers all chart needs); Plotly.js deferred to P2 on demand |
| **Q7** | **Alert-channel priority**: Do Slack / WeChat Work / email all need to ship in P0? | Infrastructure | P0: email + WeChat Work (commonly used by the domestic team); Slack deferred to P1 |
| **Q8** | **Factor-evaluation storage strategy**: Evaluating every factor daily / weekly can produce large volumes | Factor Service + DB | Factor values in Parquet (columnar compression); evaluation summaries in PostgreSQL (IC / IR / status only); detailed reports as JSON files |
| **Q9** | **Model-file storage location**: Trained PyTorch artifacts can be hundreds of MB | Model Train / Infer Service | Store under `models/{model_name}/{version}/`; map the MLflow artifact path to that directory; do not commit to Git |
| **Q10** | **Walk-forward split default parameters**: Length of train and validation windows | Model Train Service | P0: 2 years train + 6 months validation, rolling 3 folds; tunable via config |
| **Q11** | **Portfolio-optimization rebalance frequency**: Daily / weekly / monthly? | Execution Service | P0: daily pre-market rebalance (daily factors + daily signals), execute during the session; post-market signals stay unchanged |
| **Q12** | **Frontend SPA build-artifact deployment**: Embed in FastAPI (as in v1) or a separate Nginx service? | Deployment | Dev: Vite dev server (port 5180) proxies to the API; prod: `npm run build` artifacts hosted by Nginx, deployed independently of the API |

---

*Document version: v1.0 | Author: Bob (Architect) | Date: 2025-07-17*

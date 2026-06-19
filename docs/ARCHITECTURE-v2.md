# Architecture: Quant AI Trader v2 — 头部量化基金级 AI 交易系统

| 项目 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 作者 | Bob (Architect) |
| 日期 | 2025-07-17 |
| 状态 | 设计完成，待评审 |
| 依赖 PRD | `docs/PRD-v2.md` |

---

## 目录

1. [实现方案 + 框架选型](#1-实现方案--框架选型)
2. [文件列表](#2-文件列表)
3. [数据结构和接口](#3-数据结构和接口)
4. [程序调用流程](#4-程序调用流程)
5. [任务列表](#5-任务列表)
6. [依赖包列表](#6-依赖包列表)
7. [共享知识](#7-共享知识)
8. [待明确事项](#8-待明确事项)

---

## 1. 实现方案 + 框架选型

### 1.1 总体架构：六微服务 + API Gateway

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Nginx / Traefik (反向代理)                         │
│                    Vue 3 SPA (Port 5180) + API (Port 8001)            │
├───────────┬──────────┬──────────┬───────────┬──────────┬──────────────┤
│  Data Svc │ Factor   │ Model    │ Model     │ Risk     │ Execution    │
│  (8011)   │ Calc     │ Train    │ Infer     │ Model    │ Engine       │
│           │ (8012)   │ (8013)   │ (8014)    │ (8015)   │ (8016)       │
├───────────┴──────────┴──────────┴───────────┴──────────┴──────────────┤
│                         Shared Infrastructure                          │
│  PostgreSQL  │  Redis (Stream+Cache+PubSub)  │  Parquet (行情存储)     │
│  MLflow      │  Prometheus + Grafana         │  Alert Manager          │
└──────────────────────────────────────────────────────────────────────┘
```

**设计原则**：
- 每个微服务是一个独立的 FastAPI 子应用，统一挂在 API Gateway 下
- P0 阶段单机 Docker Compose 部署（所有服务共享容器编排），服务间通过 HTTP + Redis Pub/Sub 通信
- 各服务无状态（状态外存 Redis/PostgreSQL），支持独立扩缩容

### 1.2 核心技术栈定版

| 层面 | 技术选型 | 版本 | 选型理由 |
|------|----------|------|----------|
| **语言** | Python | 3.11+ | 量化生态最完整：numpy/pandas/scipy/PyTorch |
| **API 框架** | FastAPI | ≥0.110 | 异步高性能、自动 OpenAPI、WebSocket 原生支持 |
| **ASGI Server** | Uvicorn + Gunicorn | ≥0.25 | 生产级部署、多 worker + UVLoop |
| **深度学习** | PyTorch | ≥2.2 | 灵活的动态图、Transformer/TFT 原生实现 |
| **GBDT** | XGBoost / LightGBM / CatBoost | latest | 三选一，GPU 加速 |
| **ML Tracking** | MLflow | ≥2.10 | 实验追踪、模型注册、超参记录 |
| **超参搜索** | Optuna | ≥3.5 | 贝叶斯搜索、分布式并行 |
| **关系数据库** | PostgreSQL + asyncpg | 16+ | 元数据、订单、持仓、因子评估结果 |
| **缓存/消息** | Redis | 7+ | Stream（实时行情）、Pub/Sub（服务间通知）、Cache |
| **列存** | Apache Parquet (pyarrow) | — | 海量 OHLCV 行情压缩存储 |
| **组合优化** | cvxpy + OSQP | ≥1.4 | 凸优化开源求解器 |
| **前端** | Vue 3 + Vite + ECharts 5 | latest | 延续 v1 生态，团队经验 |
| **容器** | Docker Compose | — | P0 单机编排，P2 迁移 K8s |
| **日志** | Loguru | ≥0.7 | 结构化日志、自动 rotation |
| **配置** | Pydantic Settings + .env | ≥2.7 | 类型安全的配置管理、环境变量 |

### 1.3 核心难点与解决方案

| 难点 | 解决方案 |
|------|----------|
| **前视偏差** | Walk-Forward 训练框架：按时间切割，训练集仅包含 t-1 之前的数据，验证集严格后置 |
| **协方差矩阵病态** | Ledoit-Wolf Shrinkage + 指数半衰加权(60天)，条件数 > 1e6 时自动回退到收缩估计 |
| **GBDT GPU 训练不稳定** | CPU 训练优先（通过 `device` 配置，GPU-ready），使用 joblib 并行 |
| **Transformer 梯度爆炸** | Gradient Clipping(1.0) + LayerNorm + Warmup LR Scheduler |
| **组合优化约束冲突** | 分层求解：先放宽约束检查可行性，再逐步收紧；不可行时返回"最宽松可行解" |
| **数据源速率限制** | Redis 缓存层：yfinance 日频全量，Tiger API 实时推流，EODHD 备份 |
| **实盘安全性** | 熔断器（日亏5%→暂停） + 订单确认二次验证 + 最大单笔金额硬上限 |

### 1.4 部署架构（P0 Docker Compose）

```
docker-compose.yml:
  postgres (5432)
  redis (6379)
  api-gateway (8001)     ← FastAPI 主网关 + 前端 SPA
  data-service (8011)     ← 数据采集/清洗管线
  factor-service (8012)   ← 因子计算/评估
  model-train-service (8013) ← 模型训练离线任务
  model-infer-service (8014) ← 模型推理在线服务
  risk-service (8015)     ← 风险模型计算
  execution-service (8016) ← 订单执行/老虎API
  mlflow (5000)
```

---

## 2. 文件列表

### 2.1 项目根目录

```
quant-ai-trader/
├── .env.example                          # 环境变量模板
├── .gitignore
├── .pre-commit-config.yaml
├── docker-compose.yml                    # P0 单机部署
├── Dockerfile.api                        # API Gateway 镜像
├── Dockerfile.data                       # Data Service 镜像
├── Dockerfile.factor                     # Factor Service 镜像
├── Dockerfile.model-train                # Model Train Service 镜像
├── Dockerfile.model-infer                # Model Infer Service 镜像
├── Dockerfile.risk                       # Risk Service 镜像
├── Dockerfile.execution                  # Execution Service 镜像
├── Makefile                               # 开发脚本
├── pyproject.toml                         # 项目元数据 + 工具配置
├── README.md
├── _v1_archive/                           # v1 代码归档
│
├── configs/
│   ├── __init__.py
│   ├── settings.py                        # 全局配置 (Pydantic Settings)
│   ├── market_universe.py                 # 五市场股票池定义 (800+ stocks)
│   ├── factor_registry.py                 # 因子注册表 (100+ 因子定义)
│   └── risk_limits.py                     # 风控阈值配置
│
├── shared/                                # 跨服务共享模块
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py                  # 统一异常体系
│   │   ├── logger.py                      # Loguru 工厂
│   │   ├── helpers.py                     # 通用工具函数
│   │   └── datetime_utils.py              # 交易日历/时间处理
│   ├── database/
│   │   ├── __init__.py
│   │   ├── engine.py                      # asyncpg 连接池
│   │   ├── session.py                     # 会话管理
│   │   └── migrations/                    # Alembic 迁移脚本
│   ├── models/                            # SQLAlchemy ORM 模型 (共享)
│   │   ├── __init__.py
│   │   ├── base.py                        # 基类 (id, created_at, updated_at)
│   │   ├── market_data.py                 # symbol, bar, tick 表
│   │   ├── factor.py                      # factor_value, factor_eval 表
│   │   ├── model.py                       # model_version, experiment 表
│   │   ├── portfolio.py                   # position, trade, portfolio_snapshot 表
│   │   └── execution.py                   # order, execution_report 表
│   ├── redis_client.py                    # Redis 连接 (Stream + Pub/Sub + Cache)
│   ├── schema.py                          # 跨服务 Pydantic Schema
│   └── types.py                           # 共享类型别名
│
├── services/                              # 六大微服务
│   ├── data_service/
│   │   ├── __init__.py
│   │   ├── main.py                        # FastAPI 子应用入口
│   │   ├── config.py                      # 服务级配置
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py                  # REST 端点
│   │   ├── ingestion/
│   │   │   ├── __init__.py
│   │   │   ├── yfinance_client.py         # yfinance 封装
│   │   │   ├── tiger_client.py            # Tiger OpenAPI 封装
│   │   │   ├── eodhd_client.py            # EODHD 备份数据源
│   │   │   └── fred_client.py             # FRED 宏观数据
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   ├── cleanser.py                # 数据清洗 (缺失值/异常检测)
│   │   │   ├── normalizer.py              # 标准化/归一化
│   │   │   └── aggregator.py              # 多市场数据融合
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── parquet_store.py           # Parquet 读写
│   │   │   └── metadata_store.py          # PostgreSQL 元数据索引
│   │   ├── realtime/
│   │   │   ├── __init__.py
│   │   │   ├── ws_consumer.py             # WebSocket 消费者
│   │   │   └── stream_writer.py           # Redis Stream 写入
│   │   └── tasks.py                        # 预取/定时任务
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
│   │   │   ├── factor_base.py             # Factor 抽象基类
│   │   │   └── factor_engine.py           # 批量因子计算引擎
│   │   ├── factors/
│   │   │   ├── __init__.py
│   │   │   ├── technical.py               # 50+ 技术因子
│   │   │   ├── fundamental.py             # 30+ 基本面因子
│   │   │   ├── alternative.py             # 20+ 另类因子
│   │   │   └── microstructure.py          # 10+ 微观结构因子
│   │   ├── evaluation/
│   │   │   ├── __init__.py
│   │   │   ├── ic_analysis.py             # IC/IR 分析
│   │   │   ├── correlation.py             # 因子相关性矩阵
│   │   │   ├── decay.py                   # 因子衰减曲线
│   │   │   ├── stratification.py          # 分层回测
│   │   │   └── fama_macbeth.py            # Fama-MacBeth 回归
│   │   ├── auto_discover/
│   │   │   ├── __init__.py
│   │   │   ├── genetic_programming.py     # 遗传编程 (P1)
│   │   │   └── candidate_pool.py          # 候选因子池 (P1)
│   │   └── neutralization/
│   │       ├── __init__.py
│   │       ├── industry_neutral.py        # 行业中性化 (P1)
│   │       ├── size_neutral.py            # 市值中性化 (P1)
│   │       └── style_neutral.py           # 风格中性化 (P1)
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
│   │   │   ├── trainer_base.py            # 训练器基类
│   │   │   ├── gbdt_trainer.py            # XGBoost/LightGBM/CatBoost
│   │   │   ├── transformer_trainer.py     # Transformer 训练器
│   │   │   ├── tcn_trainer.py             # TCN 训练器
│   │   │   ├── tft_trainer.py             # TFT 训练器
│   │   │   └── rl_trainer.py             # PPO/SAC (P1)
│   │   ├── framework/
│   │   │   ├── __init__.py
│   │   │   ├── walk_forward.py            # Walk-Forward 框架
│   │   │   ├── timeseries_cv.py           # 时间序列交叉验证
│   │   │   └── early_stopping.py          # 早期停止 + 学习率调度
│   │   ├── hyperopt/
│   │   │   ├── __init__.py
│   │   │   └── optuna_runner.py           # Optuna 超参搜索
│   │   ├── mlflow_manager.py              # MLflow 集成
│   │   └── data_loader.py                 # 训练数据加载器
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
│   │   │   ├── gbdt_model.py              # GBDT 推理模型
│   │   │   ├── transformer_model.py       # Transformer 架构定义
│   │   │   ├── tcn_model.py               # TCN 架构
│   │   │   ├── tft_model.py               # TFT 架构
│   │   │   └── rl_model.py               # RL 策略模型 (P1)
│   │   ├── ensemble/
│   │   │   ├── __init__.py
│   │   │   ├── blender.py                 # 静态权重融合
│   │   │   ├── bayesian_weighting.py      # 动态贝叶斯加权 (P1)
│   │   │   └── market_state.py            # HMM/GARCH 市场状态 (P1)
│   │   ├── inference_engine.py            # 推理调度引擎
│   │   └── model_registry.py              # MLflow 模型加载
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
│   │   │   ├── factor_exposure.py         # 9类风格因子暴露计算
│   │   │   ├── covariance.py              # Ledoit-Wolf 协方差矩阵
│   │   │   └── specific_risk.py           # 特异性风险估计
│   │   ├── risk_measures/
│   │   │   ├── __init__.py
│   │   │   ├── var.py                     # VaR (参数法/历史/MC)
│   │   │   ├── cvar.py                    # CVaR / ES
│   │   │   └── drawdown.py               # 最大回撤
│   │   ├── stress_test/
│   │   │   ├── __init__.py
│   │   │   ├── historical_scenarios.py    # 历史极端场景 (P1)
│   │   │   └── custom_scenarios.py        # 自定义场景 (P1)
│   │   └── attribution/
│   │       ├── __init__.py
│   │       ├── brinson.py                 # Brinson 归因 (P1)
│   │       └── factor_attribution.py      # 因子归因 (P1)
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
│       │   ├── markowitz.py              # 均值方差优化
│       │   ├── black_litterman.py         # Black-Litterman
│       │   ├── risk_parity.py            # 风险平价 (P1)
│       │   └── constraints.py            # 约束系统
│       ├── backtest/
│       │   ├── __init__.py
│       │   ├── event_engine.py            # 事件驱动引擎
│       │   ├── events.py                  # 事件类型定义
│       │   ├── broker.py                  # 撮合模型
│       │   ├── slippage.py               # 滑点模型 (Almgren-Chriss)
│       │   └── metrics.py                # 绩效指标
│       ├── execution/
│       │   ├── __init__.py
│       │   ├── algo_base.py              # 算法基类
│       │   ├── twap.py                   # TWAP 切片
│       │   ├── vwap.py                   # VWAP 切片
│       │   ├── pov.py                    # POV 算法
│       │   └── tiger_executor.py         # 老虎证券执行器
│       └── monitor/
│           ├── __init__.py
│           ├── pnl_tracker.py            # 实时盈亏
│           └── circuit_breaker.py        # 熔断机制
│
├── api_gateway/
│   ├── __init__.py
│   ├── main.py                            # 主 FastAPI 应用 (挂载所有子路由)
│   ├── websocket_manager.py               # WebSocket 连接管理
│   └── middleware/
│       ├── __init__.py
│       ├── auth.py                        # API Key 认证
│       └── logging_middleware.py          # 请求日志
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
│       │   ├── index.ts                   # Pinia 入口
│       │   ├── useFactorStore.ts
│       │   ├── useModelStore.ts
│       │   ├── useRiskStore.ts
│       │   ├── usePortfolioStore.ts
│       │   └── useExecutionStore.ts
│       ├── api/
│       │   ├── index.ts                   # Axios 实例
│       │   ├── dataApi.ts
│       │   ├── factorApi.ts
│       │   ├── modelApi.ts
│       │   ├── riskApi.ts
│       │   └── executionApi.ts
│       ├── views/
│       │   ├── Dashboard.vue              # 主仪表盘
│       │   ├── FactorResearch.vue         # 因子研究页
│       │   ├── ModelCenter.vue            # 模型中心
│       │   ├── RiskDashboard.vue          # 风险仪表盘
│       │   ├── PortfolioOptimizer.vue     # 组合优化
│       │   ├── BacktestAnalysis.vue       # 回测分析
│       │   └── ExecutionMonitor.vue       # 执行监控
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
│   ├── init_db.py                          # 数据库初始化
│   ├── ingest_historical.py               # 历史数据批量导入
│   ├── run_backtest.py                     # 回测 CLI
│   └── seed_factors.py                     # 因子种子数据
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

## 3. 数据结构和接口

### 3.1 核心数据模型 (SQLAlchemy ORM)

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

### 3.2 服务核心类图

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

### 3.3 REST API 端点汇总

#### API Gateway (Port 8001)

| Method | Path | Service | Description |
|--------|------|---------|-------------|
| `GET` | `/health` | Gateway | 健康检查 |
| `WS` | `/ws` | Gateway | 实时数据 WebSocket |
| `GET` | `/api/v2/data/symbols` | Data | 股票池列表 |
| `GET` | `/api/v2/data/bars/{ticker}` | Data | 历史K线 |
| `GET` | `/api/v2/data/bars/{ticker}/minute` | Data | 分钟K线 |
| `GET` | `/api/v2/data/realtime/{ticker}` | Data | 实时报价 |
| `POST` | `/api/v2/data/ingest` | Data | 触发数据采集 |
| `GET` | `/api/v2/factors/list` | Factor | 因子列表+指标 |
| `GET` | `/api/v2/factors/{name}/analysis` | Factor | 单因子分析 |
| `GET` | `/api/v2/factors/matrix` | Factor | 因子值矩阵 |
| `POST` | `/api/v2/factors/compute` | Factor | 计算当日因子 |
| `GET` | `/api/v2/factors/correlation` | Factor | 因子相关性矩阵 |
| `GET` | `/api/v2/factors/decay/{name}` | Factor | 因子衰减曲线 |
| `POST` | `/api/v2/models/train` | Train | 启动训练 |
| `GET` | `/api/v2/models/train/status/{run_id}` | Train | 训练状态 |
| `GET` | `/api/v2/models/versions` | Train/Infer | 模型版本列表 |
| `POST` | `/api/v2/models/hyperopt` | Train | 启动超参搜索 |
| `POST` | `/api/v2/models/predict` | Infer | 批量推理 |
| `GET` | `/api/v2/models/signals` | Infer | 当日信号 |
| `GET` | `/api/v2/models/features/{ticker}` | Infer | SHAP 特征重要性 |
| `GET` | `/api/v2/risk/exposures` | Risk | Barra 因子暴露 |
| `GET` | `/api/v2/risk/var` | Risk | VaR/CVaR 指标 |
| `GET` | `/api/v2/risk/covariance` | Risk | 协方差矩阵 |
| `POST` | `/api/v2/risk/stress-test` | Risk | 压力测试 (P1) |
| `GET` | `/api/v2/risk/attribution` | Risk | 绩效归因 (P1) |
| `POST` | `/api/v2/portfolio/optimize` | Exec | 组合优化 |
| `GET` | `/api/v2/portfolio/frontier` | Exec | 有效前沿 |
| `GET` | `/api/v2/portfolio/holdings` | Exec | 当前持仓 |
| `POST` | `/api/v2/portfolio/rebalance` | Exec | 执行再平衡 |
| `POST` | `/api/v2/backtest/run` | Exec | 运行回测 |
| `GET` | `/api/v2/backtest/result/{run_id}` | Exec | 回测结果 |
| `GET` | `/api/v2/backtest/report/{run_id}` | Exec | 回测报告 |
| `POST` | `/api/v2/execution/order` | Exec | 提交订单 |
| `GET` | `/api/v2/execution/orders` | Exec | 订单列表 |
| `GET` | `/api/v2/execution/pnl` | Exec | 实时盈亏 |
| `GET` | `/api/v2/execution/circuit-breaker` | Exec | 熔断状态 |

### 3.4 统一响应格式

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

## 4. 程序调用流程

### 4.1 训练流程 (Walk-Forward + MLflow)

```mermaid
sequenceDiagram
    participant User as 用户/前端
    participant GW as API Gateway
    participant Train as Model Train Service
    participant Data as Data Service
    participant Factor as Factor Service
    participant MLflow as MLflow Server
    participant PG as PostgreSQL
    participant Disk as Parquet Store

    User->>GW: POST /api/v2/models/train {model_type, config}
    GW->>Train: 转发训练请求
    Train->>MLflow: create_experiment(name)
    MLflow-->>Train: experiment_id
    
    Train->>Data: GET /api/v2/data/bars?tickers=ALL&period=2y
    Data->>Disk: read parquet files
    Disk-->>Data: OHLCV DataFrame
    Data-->>Train: OHLCV data
    
    Train->>Factor: POST /api/v2/factors/compute {start_date, end_date}
    Factor->>Factor: 批量计算 100+ 因子
    Factor-->>Train: factor_matrix
    
    loop Walk-Forward Split (k=3)
        Train->>Train: 划分 train/val 时间窗口
        Train->>Train: 特征标准化 (fit on train)
        Train->>MLflow: start_run()
        
        Train->>Train: model.fit(X_train, y_train)
        Train->>Train: pred = model.predict(X_val)
        Train->>Train: 计算 IC/Sharpe/max_dd
        
        Train->>MLflow: log_params(config)
        Train->>MLflow: log_metrics({ic, sharpe, ...})
        Train->>MLflow: log_model(model_artifact)
        Train->>MLflow: end_run()
    end
    
    Train->>PG: INSERT model_version (version, path, metrics)
    Train->>MLflow: register_model(best_model)
    Train-->>GW: {status: "completed", run_id, metrics}
    GW-->>User: 训练完成 + 评估指标
```

### 4.2 推理 + 交易流程 (T+0 盘前/盘中)

```mermaid
sequenceDiagram
    participant Cron as 定时调度
    participant GW as API Gateway
    participant Data as Data Service
    participant Factor as Factor Service
    participant Infer as Model Infer Service
    participant Risk as Risk Service
    participant Exec as Execution Service
    participant Tiger as Tiger OpenAPI
    participant Redis as Redis Stream
    participant PG as PostgreSQL

    Note over Cron,PG: ===== T+0 盘前 (08:00) =====
    Cron->>GW: POST /api/v2/data/ingest
    GW->>Data: 触发全市场数据采集
    Data->>Data: yfinance 批量拉取 OHLCV
    Data->>Disk: 写入 Parquet
    Data->>PG: 更新元数据索引

    Cron->>GW: POST /api/v2/factors/compute
    GW->>Factor: 计算当日因子
    Factor->>Data: 获取最新行情
    Factor->>Factor: 向量化批量计算 100+ 因子
    Factor->>PG: 写入 factor_values
    Factor-->>GW: 因子计算完成

    Cron->>GW: POST /api/v2/models/predict
    GW->>Infer: 批量推理
    Infer->>MLflow: load latest model
    Infer->>Factor: GET /api/v2/factors/matrix
    Infer->>Infer: ensemble.predict(factor_matrix)
    Infer->>PG: 写入 signals
    Infer-->>GW: {signals: [...], timestamp}

    GW->>Risk: GET /api/v2/risk/covariance
    Risk->>Risk: Ledoit-Wolf 协方差矩阵

    GW->>Exec: POST /api/v2/portfolio/optimize
    Exec->>Infer: 获取信号 (作为 BL views)
    Exec->>Risk: 获取协方差矩阵
    Exec->>Exec: Black-Litterman + Markowitz 优化
    Exec-->>GW: {target_holdings: [...], trades: [...]}

    Note over Cron,PG: ===== T+0 盘中 (09:30-16:00) =====
    Tiger->>Data: WebSocket 实时行情推送
    Data->>Redis: XADD stream:market_ticks
    Redis-->>GW: Pub/Sub 广播市场数据
    GW->>GW: WebSocket 推送到前端

    loop 每 10 分钟
        Exec->>Exec: TWAP/VWAP 订单切片执行
        Exec->>Tiger: 提交子订单
        Tiger-->>Exec: 成交确认
        
        Exec->>Risk: 实时风控检查
        Risk->>Risk: 检查熔断条件
        Risk-->>Exec: {passed: true/false}
        
        alt 熔断触发
            Exec->>Exec: 暂停交易 + 告警
            Exec->>PG: 记录熔断事件
        end
        
        Exec->>PG: 更新持仓/订单
        Exec->>Redis: PUBLISH trade_updates
    end

    Note over Cron,PG: ===== T+0 盘后 (16:30) =====
    Cron->>Exec: POST /api/v2/backtest/report
    Exec->>Exec: 计算当日绩效指标
    Exec->>PG: 写入 portfolio_snapshot
```

### 4.3 实时数据流 (WebSocket + Redis Stream)

```mermaid
sequenceDiagram
    participant Tiger as Tiger WS API
    participant Data as Data Service
    participant Redis as Redis
    participant GW as API Gateway
    participant FE as Vue 3 前端
    participant PG as PostgreSQL

    Data->>Tiger: 订阅实时行情 (800+ tickers)
    
    loop 实时推送
        Tiger->>Data: WebSocket tick data
        Data->>Data: 格式规范化 + 多市场时区转换
        
        par 写入 Redis Stream
            Data->>Redis: XADD stream:market_ticks * ticker price volume
        and 更新实时缓存
            Data->>Redis: SET ticker:{symbol} {price, change, ...}
        and 广播到 Gateway
            Data->>GW: HTTP POST /api/push/tick
        end
        
        GW->>GW: 检查熔断状态
        GW->>FE: WebSocket 推送 {type: "market_tick", data}
        FE->>FE: 更新图表 (ECharts 5)
        
        alt 每 60 秒
            Data->>PG: 批量插入 tick 记录 (异步)
        end
    end
    
    Note over Data,PG: 盘后 (16:00+)
    Data->>Data: 停止实时流
    Data->>PG: 归档当日 tick → 日线 bar
    Data->>Disk: 写入 Parquet (日期分区)
```

---

## 5. 任务列表

> **⚠️ HARD LIMITS**: 最多 5 个任务。每个任务至少包含 3 个相关文件。按功能模块分组，不按单个文件拆分。

| Task ID | Task Name | Source Files | Dependencies | Priority |
|---------|-----------|-------------|--------------|----------|
| **T01** | **项目基础设施 + 配置 + 共享模块** | `pyproject.toml`, `docker-compose.yml`, `Dockerfile.*`×7, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, `Makefile`, `configs/__init__.py`, `configs/settings.py`, `configs/market_universe.py`, `configs/factor_registry.py`, `configs/risk_limits.py`, `shared/__init__.py`, `shared/core/__init__.py`, `shared/core/exceptions.py`, `shared/core/logger.py`, `shared/core/helpers.py`, `shared/core/datetime_utils.py`, `shared/database/__init__.py`, `shared/database/engine.py`, `shared/database/session.py`, `shared/database/migrations/`, `shared/models/__init__.py`, `shared/models/base.py`, `shared/models/market_data.py`, `shared/models/factor.py`, `shared/models/model.py`, `shared/models/portfolio.py`, `shared/models/execution.py`, `shared/redis_client.py`, `shared/schema.py`, `shared/types.py`, `api_gateway/__init__.py`, `api_gateway/main.py`, `api_gateway/websocket_manager.py`, `api_gateway/middleware/__init__.py`, `api_gateway/middleware/auth.py`, `api_gateway/middleware/logging_middleware.py`, `scripts/init_db.py`, `tests/conftest.py`, `frontend/index.html`, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`, `frontend/src/main.ts`, `frontend/src/App.vue`, `frontend/src/router/index.ts`, `frontend/src/api/index.ts`, `frontend/src/assets/styles/main.css` | — (无依赖) | P0 |
| **T02** | **数据服务 + 因子服务 (数据管线端到端)** | `services/data_service/__init__.py`, `services/data_service/main.py`, `services/data_service/config.py`, `services/data_service/api/__init__.py`, `services/data_service/api/routes.py`, `services/data_service/ingestion/__init__.py`, `services/data_service/ingestion/yfinance_client.py`, `services/data_service/ingestion/tiger_client.py`, `services/data_service/ingestion/eodhd_client.py`, `services/data_service/ingestion/fred_client.py`, `services/data_service/pipeline/__init__.py`, `services/data_service/pipeline/cleanser.py`, `services/data_service/pipeline/normalizer.py`, `services/data_service/pipeline/aggregator.py`, `services/data_service/storage/__init__.py`, `services/data_service/storage/parquet_store.py`, `services/data_service/storage/metadata_store.py`, `services/data_service/realtime/__init__.py`, `services/data_service/realtime/ws_consumer.py`, `services/data_service/realtime/stream_writer.py`, `services/data_service/tasks.py`, `services/factor_service/__init__.py`, `services/factor_service/main.py`, `services/factor_service/config.py`, `services/factor_service/api/__init__.py`, `services/factor_service/api/routes.py`, `services/factor_service/engine/__init__.py`, `services/factor_service/engine/factor_base.py`, `services/factor_service/engine/factor_engine.py`, `services/factor_service/factors/__init__.py`, `services/factor_service/factors/technical.py`, `services/factor_service/factors/fundamental.py`, `services/factor_service/factors/alternative.py`, `services/factor_service/factors/microstructure.py`, `services/factor_service/evaluation/__init__.py`, `services/factor_service/evaluation/ic_analysis.py`, `services/factor_service/evaluation/correlation.py`, `services/factor_service/evaluation/decay.py`, `services/factor_service/evaluation/stratification.py`, `services/factor_service/evaluation/fama_macbeth.py`, `scripts/seed_factors.py`, `scripts/ingest_historical.py`, `tests/test_data_service/`, `tests/test_factor_service/` | T01 | P0 |
| **T03** | **模型训练 + 模型推理服务 (AI 引擎端到端)** | `services/model_train_service/__init__.py`, `services/model_train_service/main.py`, `services/model_train_service/config.py`, `services/model_train_service/api/__init__.py`, `services/model_train_service/api/routes.py`, `services/model_train_service/trainers/__init__.py`, `services/model_train_service/trainers/trainer_base.py`, `services/model_train_service/trainers/gbdt_trainer.py`, `services/model_train_service/trainers/transformer_trainer.py`, `services/model_train_service/trainers/tcn_trainer.py`, `services/model_train_service/trainers/tft_trainer.py`, `services/model_train_service/trainers/rl_trainer.py`, `services/model_train_service/framework/__init__.py`, `services/model_train_service/framework/walk_forward.py`, `services/model_train_service/framework/timeseries_cv.py`, `services/model_train_service/framework/early_stopping.py`, `services/model_train_service/hyperopt/__init__.py`, `services/model_train_service/hyperopt/optuna_runner.py`, `services/model_train_service/mlflow_manager.py`, `services/model_train_service/data_loader.py`, `services/model_infer_service/__init__.py`, `services/model_infer_service/main.py`, `services/model_infer_service/config.py`, `services/model_infer_service/api/__init__.py`, `services/model_infer_service/api/routes.py`, `services/model_infer_service/models/__init__.py`, `services/model_infer_service/models/gbdt_model.py`, `services/model_infer_service/models/transformer_model.py`, `services/model_infer_service/models/tcn_model.py`, `services/model_infer_service/models/tft_model.py`, `services/model_infer_service/models/rl_model.py`, `services/model_infer_service/ensemble/__init__.py`, `services/model_infer_service/ensemble/blender.py`, `services/model_infer_service/ensemble/bayesian_weighting.py`, `services/model_infer_service/ensemble/market_state.py`, `services/model_infer_service/inference_engine.py`, `services/model_infer_service/model_registry.py`, `tests/test_model_service/` | T01, T02 (需要 factor 计算的因子数据) | P0 |
| **T04** | **风险服务 + 执行服务 (风控 + 回测 + 组合优化 + 执行)** | `services/risk_service/__init__.py`, `services/risk_service/main.py`, `services/risk_service/config.py`, `services/risk_service/api/__init__.py`, `services/risk_service/api/routes.py`, `services/risk_service/barra/__init__.py`, `services/risk_service/barra/factor_exposure.py`, `services/risk_service/barra/covariance.py`, `services/risk_service/barra/specific_risk.py`, `services/risk_service/risk_measures/__init__.py`, `services/risk_service/risk_measures/var.py`, `services/risk_service/risk_measures/cvar.py`, `services/risk_service/risk_measures/drawdown.py`, `services/risk_service/stress_test/__init__.py`, `services/risk_service/stress_test/historical_scenarios.py`, `services/risk_service/stress_test/custom_scenarios.py`, `services/risk_service/attribution/__init__.py`, `services/risk_service/attribution/brinson.py`, `services/risk_service/attribution/factor_attribution.py`, `services/execution_service/__init__.py`, `services/execution_service/main.py`, `services/execution_service/config.py`, `services/execution_service/api/__init__.py`, `services/execution_service/api/routes.py`, `services/execution_service/optimizer/__init__.py`, `services/execution_service/optimizer/markowitz.py`, `services/execution_service/optimizer/black_litterman.py`, `services/execution_service/optimizer/risk_parity.py`, `services/execution_service/optimizer/constraints.py`, `services/execution_service/backtest/__init__.py`, `services/execution_service/backtest/event_engine.py`, `services/execution_service/backtest/events.py`, `services/execution_service/backtest/broker.py`, `services/execution_service/backtest/slippage.py`, `services/execution_service/backtest/metrics.py`, `services/execution_service/execution/__init__.py`, `services/execution_service/execution/algo_base.py`, `services/execution_service/execution/twap.py`, `services/execution_service/execution/vwap.py`, `services/execution_service/execution/pov.py`, `services/execution_service/execution/tiger_executor.py`, `services/execution_service/monitor/__init__.py`, `services/execution_service/monitor/pnl_tracker.py`, `services/execution_service/monitor/circuit_breaker.py`, `scripts/run_backtest.py`, `tests/test_risk_service/`, `tests/test_execution_service/` | T01, T02 (需要数据和因子), T03 (需要推理信号) | P0 |
| **T05** | **前端 SPA + 系统集成 + 告警 + 联调** | `frontend/src/stores/index.ts`, `frontend/src/stores/useFactorStore.ts`, `frontend/src/stores/useModelStore.ts`, `frontend/src/stores/useRiskStore.ts`, `frontend/src/stores/usePortfolioStore.ts`, `frontend/src/stores/useExecutionStore.ts`, `frontend/src/api/dataApi.ts`, `frontend/src/api/factorApi.ts`, `frontend/src/api/modelApi.ts`, `frontend/src/api/riskApi.ts`, `frontend/src/api/executionApi.ts`, `frontend/src/views/Dashboard.vue`, `frontend/src/views/FactorResearch.vue`, `frontend/src/views/ModelCenter.vue`, `frontend/src/views/RiskDashboard.vue`, `frontend/src/views/PortfolioOptimizer.vue`, `frontend/src/views/BacktestAnalysis.vue`, `frontend/src/views/ExecutionMonitor.vue`, `frontend/src/components/layout/AppHeader.vue`, `frontend/src/components/layout/AppSidebar.vue`, `frontend/src/components/layout/AppLayout.vue`, `frontend/src/components/dashboard/AccountSummary.vue`, `frontend/src/components/dashboard/MarketStatusBar.vue`, `frontend/src/components/factor/FactorTable.vue`, `frontend/src/components/factor/ICRankChart.vue`, `frontend/src/components/factor/FactorCorrHeatmap.vue`, `frontend/src/components/factor/DecayCurve.vue`, `frontend/src/components/model/ModelStatusCard.vue`, `frontend/src/components/model/SHAPImportance.vue`, `frontend/src/components/model/PredVsActual.vue`, `frontend/src/components/risk/BarraRadar.vue`, `frontend/src/components/risk/VaRGauge.vue`, `frontend/src/components/risk/SectorPie.vue`, `frontend/src/components/portfolio/EfficientFrontier.vue`, `frontend/src/components/portfolio/RebalanceTable.vue`, `frontend/src/components/execution/OrderSliceProgress.vue`, `frontend/src/components/execution/CircuitBreakerStatus.vue` | T01, T02, T03, T04 (所有后端服务就绪) | P0 |

### 5.1 任务依赖图

```mermaid
graph TD
    T01["T01: 项目基础设施 + 配置 + 共享模块<br/>(~50 files)"]
    T02["T02: 数据服务 + 因子服务<br/>(~43 files)"]
    T03["T03: 模型训练 + 模型推理服务<br/>(~38 files)"]
    T04["T04: 风险服务 + 执行服务<br/>(~47 files)"]
    T05["T05: 前端 SPA + 系统集成 + 联调<br/>(~37 files)"]

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

## 6. 依赖包列表

### 6.1 核心依赖 (`pyproject.toml` dependencies)

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
# wechat-work-bot (企业微信)

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

### 6.2 前端依赖 (`frontend/package.json`)

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

## 7. 共享知识

### 7.1 命名规范

| 层面 | 规范 | 示例 |
|------|------|------|
| **Python 文件** | snake_case | `factor_engine.py`, `walk_forward.py` |
| **Python 类** | PascalCase | `FactorEngine`, `WalkForwardFramework` |
| **Python 函数/方法** | snake_case | `compute_all()`, `get_historical_data()` |
| **Python 常量** | UPPER_SNAKE | `FACTOR_CATEGORIES`, `MAX_POSITION_SIZE` |
| **数据库表名** | snake_case 复数 | `daily_bars`, `factor_values`, `orders` |
| **数据库列名** | snake_case | `trade_date`, `factor_name`, `avg_cost` |
| **API 路径** | kebab-case | `/api/v2/factors/correlation` |
| **TypeScript 文件** | camelCase (special) -> `use` prefix for stores | `useFactorStore.ts`, `dataApi.ts` |
| **Vue 组件** | PascalCase | `FactorTable.vue`, `VaRGauge.vue` |
| **Docker 镜像** | lowercase-hyphen | `quant-factor-service` |
| **Git 分支** | `feature/`, `fix/`, `chore/` prefix | `feature/walk-forward-trainer` |

### 7.2 配置管理

- 所有配置通过 `configs/settings.py` 中的 Pydantic `BaseSettings` 管理
- 环境变量前缀: `QAT_` (Quant AI Trader)
- `.env` 文件位于项目根目录，不提交到 Git
- 各服务有独立 `config.py` 继承基类，覆盖服务特定配置
- 敏感信息 (TIGER_PRIVATE_KEY, DB_PASSWORD) 必须通过环境变量注入

```python
# settings.py 示例
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

### 7.3 异常处理

```python
# shared/core/exceptions.py
class QuantAIException(Exception):
    """所有自定义异常的基类"""
    def __init__(self, message: str, code: int = 9000, detail: dict = None):
        self.message = message
        self.code = code
        self.detail = detail or {}

class DataSourceUnavailable(QuantAIException):
    """数据源不可用 (code: 2001)"""

class ModelNotReady(QuantAIException):
    """模型未训练/未加载 (code: 3001)"""

class RiskCheckFailed(QuantAIException):
    """风控检查不通过 (code: 4001)"""

class CircuitBreakerTripped(QuantAIException):
    """熔断已触发 (code: 4002)"""

class ExecutionRejected(QuantAIException):
    """订单执行被拒绝 (code: 5001)"""
```

### 7.4 日志规范

- 所有服务使用 `loguru` 统一日志
- 格式: `{time:ISO} | {level: <8} | {service}:{module}:{line} | {message}`
- 级别: DEBUG < INFO < WARNING < ERROR < CRITICAL
- INFO: 关键业务节点（数据拉取完成、因子计算完成、模型加载、订单成交）
- WARNING: 可恢复异常（数据源重试、缓存未命中、约束放宽）
- ERROR: 需要关注异常（数据源失败、模型加载失败、订单被拒）
- 日志文件: `logs/{service}/{date}.log`, 自动 rotation (100MB/文件, 保留30天)
- 生产环境 INFO, 开发环境 DEBUG

### 7.5 数据格式约定

- 所有时间戳: ISO 8601 UTC (`2025-07-17T10:30:00Z`)
- 数据库日期列: `date` 类型 (无时区)
- 股票代码: 统一大写, 港股加 `.HK` 后缀, 新加坡 `.SI`, 澳洲 `.AX`, 新西兰 `.NZ`
- 货币: 统一以 USD 计价存储, 多币种转换使用 `configs/settings.py` 中的汇率表
- Parquet 分区: `market={market}/year={YYYY}/month={MM}/` (Hive-style)
- 因子值: float64, NaN 表示缺失 (自动前向填充)
- 缺失值标记: -99999 用于特别标记的缺失值

### 7.6 数值精度与类型

- 价格: `Decimal(10, 4)` 在 PostgreSQL, `float64` 在内存
- 数量: `int` (整数股)
- 权重: `float64`, 范围 [0, 1]
- 收益率: `float64`, 小数形式 (0.01 = 1%)
- 协方差矩阵: `float64` ndarray
- GPU 张量: `float32` (性能优先)

### 7.7 API 设计约定

- 所有响应使用统一格式: `{code, message, data, timestamp, request_id}`
- 列表响应使用分页: `{code, data: {items, total, page, page_size}, ...}`
- 时间范围查询: `start_date`, `end_date` 参数, ISO 8601 日期格式
- 批量接口: POST body 传 `tickers: list[str]`
- 长时间运行操作 (训练/回测): 返回 `run_id`, 客户端轮询状态

### 7.8 安全约定

- Tiger API 私钥: 仅通过环境变量注入, 不得写入任何文件
- API Key 认证: `X-API-Key` header, 验证在 `api_gateway/middleware/auth.py`
- 数据库密码: 通过 Docker secrets 或环境变量
- 所有外部 API 调用: 设置 timeout (默认 30s)
- 生产环境: CORS 白名单, HTTPS only

---

## 8. 待明确事项

| # | 事项 | 影响范围 | 建议决策 |
|---|------|----------|----------|
| **Q1** | **Tiger API 程序化下单权限**：账户 20874631 是否有程序化交易权限？是否需要先签协议？ | Execution Service | 建议：P0 阶段先用 Tiger Paper Trading 环境验证下单管线，实盘账户仅做行情+持仓查询，下单先人工确认 |
| **Q2** | **yfinance 速率限制应对**：全量 800+ 标的日频拉取可能触发 Yahoo 限速 | Data Service | 建议：实现 exponential backoff + 分批次拉取 (每批 50 只, 间隔 2s)，日频数据通过缓存命中减少重复请求 |
| **Q3** | **TA-Lib 安装兼容性**：TA-Lib 需要编译 C 扩展，Windows/Mac 安装困难 | Factor Service | 建议：Docker 镜像中预编译；Windows 开发环境使用 `ta` (纯 Python) 作为 fallback |
| **Q4** | **PostgreSQL vs SQLite 过渡**：PRD 提到 P0 可能保留 SQLite | Database | 建议：P0 直接用 PostgreSQL (Docker 一行拉起)，成本为零但后续避免迁移 |
| **Q5** | **Transformer d_model 目标**：PRD 要求 d_model ≥ 512，但 P0 CPU 训练可能很慢 | Model Train Service | 建议：提供 small/large 两档配置：small (d_model=128) 用于快速验证和 CPU 训练，large (d_model=512) 用于 GPU 生产训练 |
| **Q6** | **前端是否需要 Plotly.js**：PRD Q7 提到新增 Plotly.js 用于统计图 | Frontend | 建议：P0 仅 ECharts 5（已覆盖所有图表需求），Plotly.js 留到 P2 按需引入 |
| **Q7** | **告警通道优先级**：Slack / 企业微信 / 邮件三个通道是否都需要 P0 实现 | Infrastructure | 建议：P0 实现邮件 + 企业微信（国内团队常用），Slack 留到 P1 |
| **Q8** | **因子评估存储策略**：每个因子每天/每周评估，评估结果存储量可能很大 | Factor Service + DB | 建议：因子值存 Parquet (列存压缩)，评估摘要存 PostgreSQL (仅 IC/IR/状态)，详细评估报告存 JSON 文件 |
| **Q9** | **模型文件存储位置**：训练产出的 PyTorch 模型文件大小可能数百 MB | Model Train/Infer Service | 建议：模型文件存储在 `models/{model_name}/{version}/` 目录下，MLflow artifact 路径映射到此目录；不存入 Git |
| **Q10** | **Walk-Forward 分割参数默认值**：训练窗口和验证窗口的长度 | Model Train Service | 建议：P0 使用 2 年训练 + 6 个月验证，滚动 3 折。通过配置可调 |
| **Q11** | **组合优化 rebalance 频率**：每日/每周/每月？ | Execution Service | 建议：P0 每日盘前 rebalance (日频因子 + 日频信号)，盘中执行；盘后信号保持不变 |
| **Q12** | **前端 SPA 构建产物部署**：嵌入 FastAPI (如 v1) 还是独立 Nginx 服务 | Deployment | 建议：开发环境 Vite dev server (port 5180) 代理到 API；生产环境 `npm run build` 产物由 Nginx 托管，与 API 独立部署 |

---

*文档版本: v1.0 | 作者: Bob (Architect) | 日期: 2025-07-17*

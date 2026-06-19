# Tiger API 全量数据实时同步系统架构设计

> 项目: quant-ai-trader | 账户: 20874631 | 日期: 2026-06-14
> 设计者: 架构师 | 审核: team-lead

---

## 1. 数据库扩建设计

### 1.1 现有表结构回顾

| 表名 | 记录数 | 用途 |
|------|--------|------|
| market_metadata | 空 | Parquet 元数据索引 |
| trades | 757 | 交易记录 |
| signals | 25,940 | 信号历史 |
| price_ticks | 10,377 | 价格缓存 |
| portfolio_snapshots | 129 | 组合快照 |
| portfolio_account | 1 | 账户摘要 |
| portfolio_positions | 1 | 持仓快照 |
| data/daily/*.parquet | ~ | 日线 OHLCV |

### 1.2 新增表设计

#### 表 1: `tiger_orders` — 订单历史

```sql
CREATE TABLE tiger_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE,       -- Tiger 全局订单ID
    parent_id INTEGER,                       -- 父订单ID (多腿订单)
    ticker TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'US',       -- US/HK/SG
    currency TEXT NOT NULL DEFAULT 'USD',
    action TEXT NOT NULL,                    -- BUY/SELL
    order_type TEXT NOT NULL,               -- MKT/LMT/STP/STP_LMT
    quantity REAL NOT NULL,
    filled_quantity REAL DEFAULT 0,
    limit_price REAL,
    stop_price REAL,
    avg_fill_price REAL,
    status TEXT NOT NULL,                    -- New/PartiallyFilled/Filled/Cancelled/Rejected/Expired
    outside_rth INTEGER DEFAULT 0,           -- 盘前盘后标记
    reason TEXT,                             -- 拒绝原因
    commission REAL DEFAULT 0,
    create_time TEXT NOT NULL,
    update_time TEXT NOT NULL,
    fill_time TEXT,
    cancel_time TEXT,
    source TEXT DEFAULT 'manual',            -- manual/auto/strategy
    strategy_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_tiger_orders_ticker ON tiger_orders(ticker);
CREATE INDEX idx_tiger_orders_status ON tiger_orders(status);
CREATE INDEX idx_tiger_orders_create_time ON tiger_orders(create_time);
CREATE INDEX idx_tiger_orders_order_id ON tiger_orders(order_id);
```

**用途**: 存储完整订单生命周期，替代本地 trades 表的订单追踪能力。支持策略复盘和成本分析。

**预估行数**: ~1000 (初始) → ~5000/年

#### 表 2: `tiger_transactions` — 成交明细

```sql
CREATE TABLE tiger_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL UNIQUE,
    order_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'US',
    action TEXT NOT NULL,                    -- BUY/SELL
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    commission REAL DEFAULT 0,
    trade_time TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (order_id) REFERENCES tiger_orders(order_id)
);

CREATE INDEX idx_tiger_trans_order ON tiger_transactions(order_id);
CREATE INDEX idx_tiger_trans_ticker ON tiger_transactions(ticker);
CREATE INDEX idx_tiger_trans_time ON tiger_transactions(trade_time);
```

**用途**: 精确到每笔成交的明细，用于精确 P&L 归因和滑点分析。现有 trades 表记录本地策略交易决策，此表记录 Tiger 实际执行。

**预估行数**: ~2000 (初始) → ~10000/年

#### 表 3: `stock_metadata` — 股票基本面/分类

```sql
CREATE TABLE stock_metadata (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    market TEXT NOT NULL,                    -- US/HK/SG/AU/NZ
    currency TEXT NOT NULL,
    sector TEXT,                             -- 行业(GICS)
    industry TEXT,                           -- 子行业
    market_cap REAL,                         -- 市值
    shares_outstanding REAL,                 -- 流通股
    pe_ratio REAL,                           -- 市盈率
    pb_ratio REAL,                           -- 市净率
    eps REAL,                                -- 每股收益
    dividend_yield REAL,                     -- 股息率
    beta REAL,                               -- 贝塔
    short_interest REAL,                     -- 做空比例 (%)
    short_ratio REAL,                        -- 做空比率(天数)
    exchange TEXT,                           -- 交易所
    lot_size INTEGER DEFAULT 1,              -- 整手股数
    tick_size REAL,                          -- 最小变动单位
    last_updated TEXT NOT NULL,
    source TEXT DEFAULT 'tiger'
);

CREATE INDEX idx_stock_meta_sector ON stock_metadata(sector);
CREATE INDEX idx_stock_meta_market ON stock_metadata(market);
CREATE INDEX idx_stock_meta_mcap ON stock_metadata(market_cap DESC);
```

**用途**: 替代现有空表 market_metadata，存储通过 Tiger API 获取的完整股票基本面数据。为 AI 模型提供基本面和行业分类特征。

**预估行数**: ~200 (当前关注池) → ~500 (扩展)

#### 表 4: `capital_flow` — 资金流向

```sql
CREATE TABLE capital_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,                      -- YYYY-MM-DD
    inflow REAL,                             -- 主力流入
    outflow REAL,                            -- 主力流出
    net_flow REAL,                           -- 净流入
    super_large_net REAL,                    -- 超大单净
    large_net REAL,                          -- 大单净
    medium_net REAL,                         -- 中单净
    small_net REAL,                          -- 小单净
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, date)
);

CREATE INDEX idx_capital_flow_ticker ON capital_flow(ticker);
CREATE INDEX idx_capital_flow_date ON capital_flow(date);
```

**用途**: 资金流数据作为 AI 模型情绪/资金面特征输入。

**预估行数**: ~200 × 20 天 = ~4000

#### 表 5: `market_calendar` — 交易日历

```sql
CREATE TABLE market_calendar (
    date TEXT NOT NULL,
    market TEXT NOT NULL,                    -- US/HK/SG
    is_trading_day INTEGER NOT NULL DEFAULT 1,
    open_time TEXT,
    close_time TEXT,
    pre_market_open TEXT,
    pre_market_close TEXT,
    after_hours_open TEXT,
    after_hours_close TEXT,
    holiday_name TEXT,
    PRIMARY KEY (date, market)
);

CREATE INDEX idx_market_cal_market ON market_calendar(market);
```

**用途**: 确定交易时间窗口，避免非交易时段调用 API 浪费限额。

#### 表 6: `corporate_events` — 公司事件

```sql
CREATE TABLE corporate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,               -- dividend/split/earnings
    event_date TEXT NOT NULL,
    record_date TEXT,
    pay_date TEXT,
    amount REAL,                             -- 分红金额
    split_ratio TEXT,                        -- 拆股比例 "2:1"
    eps_estimate REAL,
    eps_actual REAL,
    revenue_estimate REAL,
    revenue_actual REAL,
    surprise_pct REAL,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_corp_events_ticker ON corporate_events(ticker);
CREATE INDEX idx_corp_events_date ON corporate_events(event_date);
CREATE INDEX idx_corp_events_type ON corporate_events(event_type);
```

**用途**: 分红、拆股、财报日历，辅助风控和信号过滤。

#### 表 7: `sync_status` — 同步状态控制

```sql
CREATE TABLE sync_status (
    sync_type TEXT PRIMARY KEY,             -- orders/assets/fundamentals/etc
    last_sync_time TEXT,
    last_success_time TEXT,
    last_cursor TEXT,                        -- 分页游标
    records_synced INTEGER DEFAULT 0,
    status TEXT DEFAULT 'idle',             -- idle/running/error
    error_message TEXT,
    next_scheduled_time TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**用途**: 增量同步状态管理，记录每种数据的上次同步时间和分页游标。

### 1.3 索引策略总结

| 索引 | 表 | 用途 |
|------|-----|------|
| ticker + date | capital_flow, corporate_events | 按股票日查询 |
| order_id | tiger_orders, tiger_transactions | 订单关联查询 |
| create_time/event_date | tiger_orders, corporate_events | 时间范围查询 |
| status | tiger_orders | 按状态筛选 |
| market + date | market_calendar | 交易日判断 |
| market_cap DESC | stock_metadata | Top N 市值排序 |

### 1.4 SQLite 优化措施

现有措施保留并增强:
- `PRAGMA journal_mode=WAL` (已启用)
- `PRAGMA synchronous=NORMAL` (已启用)
- `PRAGMA cache_size=-128000` (建议提升至128MB)
- `PRAGMA mmap_size=536870912` (建议提升至512MB)
- 所有批量写入使用事务包裹 (SINGLE TRANSACTION)
- 新增 `busy_timeout=30000` 避免写锁竞争

---

## 2. 同步策略

### 2.1 API 限流模型

Tiger API 限制 **10 calls/min**，策略:

```
每分钟预算 = 10 calls
├── Tier 1 (高频): 预留 3 calls/min (实时报价)
├── Tier 2 (中频): 预留 4 calls/min (基本面/资金流)
├── Tier 3 (低频): 预留 2 calls/min (日历/公司事件)
└── 缓冲: 1 call/min (重试/突发)
```

**批量合并策略**: 使用 `get_stock_briefs([symbols])` 一次获取多只股票信息，1 call = 50 只股票。

**实际利用率**: 每日 ~3000 effective data points，仅 50 actual API calls。

### 2.2 Tier 1 — 高频同步 (30s)

**触发**: 交易时段内每 30 秒

| 数据项 | API 方法 | 备注 |
|--------|----------|------|
| 持仓实时报价 | get_stock_briefs(batch) | 1 call 覆盖所有持仓，已有缓存 |
| 持仓列表 | get_positions() | 已有 15s 缓存，保持 |

**调用频率**: 2 calls/min (briefs 批量)

### 2.3 Tier 2 — 中频同步 (5min)

**触发**: 交易时段内每 5 分钟

| 数据项 | API 方法 | 目的 | 调用次数 |
|--------|----------|------|----------|
| 资金流向 | get_capital_flow() | 主力资金追踪 | 3 calls (分3批) |
| 订单簿深度 | get_depth_quote() | 流动性评估 | 2 calls (Top 10) |
| 分时线 | get_timeline() | 日内走势 | 2 calls (活跃股) |
| 做空数据 | get_short_interest() | 空头挤压预警 | 1 call |
| 账户资产 | get_aggregate_assets() | 详细资产分析 | 1 call |

**minute-budget**: 9 calls，控制在限额内。

### 2.4 Tier 3 — 低频同步 (Daily)

**触发**: 每日盘前/盘后各一次

| 数据项 | API 方法 | 目的 |
|--------|----------|------|
| 基本面数据 | get_stock_fundamental() | PE/PB/ROE 更新 |
| 行业分类 | get_stock_industry() | 行业归属更新 |
| 行业列表 | get_industry_list() + get_industry_stocks() | 行业映射表 |
| 交易日历 | get_trading_calendar() | 交易时段规划 |
| 市场状态 | get_market_status() | 确认开盘状态 |
| 财报日历 | get_corporate_earnings_calendar() | 财报预警 |
| 分红信息 | get_corporate_dividend() | 除权除息 |
| 拆股信息 | get_corporate_split() | 拆合股处理 |
| 期权行权 | get_option_exercise_records() | 期权到期处理 |
| 资金分布 | get_capital_distribution() | 资金结构分析 |

**调用次数**: ~12 calls/day (分时段执行)

### 2.5 All-Time — 初始化全量拉取

**触发**: 系统首次部署时执行一次

| 数据项 | API 方法 | 预计数据量 | 预计耗时 |
|--------|----------|-----------|----------|
| 历史订单 | get_orders() 分页 | ~1000 条 | 10-15 min |
| 已成交订单 | get_filled_orders() | ~800 条 | 5-8 min |
| 已取消订单 | get_cancelled_orders() | ~200 条 | 3-5 min |
| 成交明细 | get_transactions() | ~2000 条 | 8-12 min |
| 全部基本面 | get_stock_fundamental(batch) | ~40 只 | 2-3 min |

**总耗时**: 约 30-45 分钟，在非交易时段执行。

### 2.6 节流控制器设计

```python
class TigerRateLimiter:
    """
    滑动窗口限流器
    - 窗口: 60 秒
    - 限制: 10 calls
    - 策略: 令牌桶 + 优先级队列
    """
    def __init__(self, max_calls=10, window=60):
        self.max_calls = max_calls
        self.window = window
        self.call_times: deque[float] = deque()
        self.pending: PriorityQueue[Tuple[int, Callable]] = []  # (priority, callable)

    def can_call(self) -> bool:
        """检查是否可以发起调用"""
        now = time.time()
        while self.call_times and self.call_times[0] < now - self.window:
            self.call_times.popleft()
        return len(self.call_times) < self.max_calls

    def wait_and_call(self, priority: int = 0):
        """等待直到可以调用（阻塞）"""
        while not self.can_call():
            time.sleep(1.0)
        self.call_times.append(time.time())
```

### 2.7 交易时段检测

```python
# 交易时段: US 9:30-16:00 ET, Pre 4:00-9:30, After 16:00-20:00
# HK 9:30-16:00 HKT
# SG 9:00-17:00 SGT
# 非交易时段自动降低同步频率 → Tier 2 降为 30min, Tier 3 不变
```

---

## 3. 文件修改清单

按实现顺序排列:

### Phase 1: 基础设施 (P0)

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 1 | **新建** | `backend/api/db.py` | 统一数据库模块，封装所有 DB 操作 |
| 2 | **修改** | `backend/data_engine/historical_store.py` | 添加新表初始化，整合到 `_init_db()` |
| 3 | **新建** | `backend/services/rate_limiter.py` | Tiger API 限流控制器 |
| 4 | **新建** | `backend/services/sync_state.py` | 同步状态管理 (读/写 sync_status 表) |

### Phase 2: Tiger API 扩展 (P0)

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 5 | **修改** | `backend/data_engine/tiger_client.py` | 添加 Trade API 扩展方法 |
| 6 | **修改** | `backend/data_engine/tiger_client.py` | 添加 Quote API 扩展方法 |
| 7 | **新建** | `backend/services/tiger_sync.py` | 核心同步协调器 |

### Phase 3: 同步引擎 (P0)

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 8 | **新建** | `backend/services/tier1_sync.py` | Tier 1 高频同步 (30s) |
| 9 | **新建** | `backend/services/tier2_sync.py` | Tier 2 中频同步 (5min) |
| 10 | **新建** | `backend/services/tier3_sync.py` | Tier 3 低频同步 (daily) |
| 11 | **新建** | `backend/services/alltime_sync.py` | 全量初始化拉取 |
| 12 | **修改** | `backend/main.py` | 集成同步服务到 lifespan |

### Phase 4: AI 特征增强 (P1)

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 13 | **新建** | `backend/data_engine/features_fundamental.py` | 基本面特征提取 |
| 14 | **新建** | `backend/data_engine/features_flow.py` | 资金流特征提取 |
| 15 | **修改** | `backend/data_engine/data_pipeline.py` | 扩展 `FEATURE_COLUMNS`，集成新特征 |
| 16 | **修改** | `backend/ai_models/predictor.py` | `n_vars` 40→60，支持新特征维度 |

### Phase 5: 前端扩展 (P1)

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 17 | **新建** | `src/components/dashboard/OrderHistory.vue` | 订单历史表格 |
| 18 | **新建** | `src/components/dashboard/CapitalFlow.vue` | 资金流向仪表板 |
| 19 | **新建** | `src/components/dashboard/FundamentalPanel.vue` | 基本面数据面板 |
| 20 | **修改** | `src/views/Dashboard.vue` | 集成新组件 |
| 21 | **修改** | `src/stores/usePortfolioStore.ts` | 添加订单/资金流/基本面状态 |
| 22 | **修改** | `src/api/dataApi.ts` | 添加新的 API 调用 |

### Phase 6: API 路由 (P1)

| # | 操作 | 文件 | 说明 |
|---|------|------|------|
| 23 | **修改** | `backend/api/routes_data.py` | 添加 Tiger 数据查询端点 |
| 24 | **新建** | `backend/api/routes_orders.py` | 订单查询端点 |
| 25 | **修改** | `backend/config.py` | 添加同步配置项 |

---

## 4. 数据管道

### 4.1 完整数据流

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Tiger Trade API                                 │
│  get_orders / get_transactions / get_assets / get_positions              │
│  get_aggregate_assets / get_analytics_asset                              │
│  get_segment_fund_available / get_segment_fund_history                   │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────────────────┐
│                          Tiger Quote API                                 │
│  get_stock_briefs / get_stock_fundamental / get_stock_industry           │
│  get_depth_quote / get_trade_ticks / get_timeline                        │
│  get_short_interest / get_capital_flow / get_capital_distribution        │
│  get_corporate_dividend / get_corporate_split / get_earnings_calendar    │
│  get_trading_calendar / get_market_status / get_industry_list            │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  rate_limiter    │  ← 滑动窗口节流 10calls/min
                    │  (令牌桶)        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼─────┐ ┌─────▼──────┐ ┌────▼─────────┐
     │ tier1_sync   │ │ tier2_sync │ │ tier3_sync   │
     │ (30s)        │ │ (5min)     │ │ (daily)      │
     │ - prices     │ │ - flow     │ │ - fundamental│
     │ - positions  │ │ - depth    │ │ - calendar   │
     │              │ │ - short    │ │ - corporate  │
     └──────┬───────┘ └─────┬──────┘ └────┬─────────┘
            │               │             │
            └───────────────┼─────────────┘
                            │
                    ┌───────▼────────┐
                    │  tiger_sync    │  ← 协调器
                    │  (orchestrator)│
                    └───────┬────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
     ┌────────▼───┐  ┌─────▼─────┐  ┌───▼──────────┐
     │  SQLite DB │  │  Parquet  │  │  Memory Cache│
     │  - orders  │  │  - ohlcv  │  │  - prices    │
     │  - trans   │  │  - ticks  │  │  - positions │
     │  - metadata│  │           │  │              │
     │  - flow    │  │           │  │              │
     └────┬───────┘  └─────┬─────┘  └──────┬───────┘
          │                │               │
          └────────────────┼───────────────┘
                           │
                  ┌────────▼────────┐
                  │  FastAPI Routes │
                  │  REST + WebSocket│
                  └────────┬────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
  ┌───────▼──────┐ ┌───────▼──────┐ ┌──────▼───────┐
  │  前端 Vue.js │ │  AI Models   │ │  Trading     │
  │  Dashboard   │ │  Predictor   │ │  Engine       │
  │  Charts      │ │  RL Agent    │ │  Executor     │
  └──────────────┘ └──────────────┘ └──────────────┘
```

### 4.2 关键数据流向

```
# 实时价格推流
Tiger get_stock_briefs → rate_limiter → tier1_sync → price_ticks 表/内存 → WebSocket → 前端

# 订单历史查询
Tiger get_orders → alltime_sync → tiger_orders 表 → /api/orders/{ticker} → 前端表格

# 基本面→AI 特征
Tiger get_stock_fundamental → tier3_sync → stock_metadata 表 → features_fundamental → DataPipeline → Predictor/RL
```

---

## 5. AI 特征增强

### 5.1 当前特征维度

当前 `DataPipeline.FEATURE_COLUMNS` = **63 维**（详见 `backend/data_engine/data_pipeline.py:19-62`），实际输入模型使用 40 维 (n_vars=40)。

### 5.2 新增特征

#### 基本面特征 (Tier 3) — 8 维

| 特征 | 来源 | 说明 |
|------|------|------|
| pe_ratio_z | stock_metadata | PE 在同行业中的 z-score |
| pb_ratio_z | stock_metadata | PB 同行业 z-score |
| eps_growth | stock_metadata | EPS 同比变化 |
| market_cap_quantile | stock_metadata | 市值分位数 |
| dividend_yield_norm | stock_metadata | 归一化股息率 |
| sector_momentum_rank | cross_stock 计算 | 行业动量排序 |
| short_interest_ratio | stock_metadata | 做空比率 |
| beta_vs_market | stock_metadata | 系统性风险 |

#### 资金流特征 (Tier 2) — 6 维

| 特征 | 来源 | 说明 |
|------|------|------|
| net_flow_ratio | capital_flow | 净流入/市值比 |
| large_order_pct | capital_flow | 大单占比 |
| flow_divergence | capital_flow | 资金-价格背离度 |
| flow_momentum_5d | capital_flow | 5日资金流动量 |
| cumulative_flow_20d | capital_flow | 20日累计净流入 |
| flow_volatility | capital_flow | 资金流波动率 |

#### 订单簿特征 (Tier 2) — 4 维

| 特征 | 来源 | 说明 |
|------|------|------|
| bid_ask_spread_pct | depth_quote | 买卖价差百分比 |
| depth_imbalance | depth_quote | 订单簿不平衡度 |
| liquidity_score | depth_quote | 流动性评分 |
| volume_weighted_depth | depth_quote | 量加权利深度 |

#### 公司事件特征 (Tier 3) — 2 维

| 特征 | 来源 | 说明 |
|------|------|------|
| days_to_earnings | corporate_events | 距财报天数 |
| dividend_ex_div_days | corporate_events | 距除息天数 |

**新增总计**: 20 维
**扩增后总维度**: 63 + 20 = **83 维** (实际输入模型从 40→60 维)

### 5.3 Predictor 修改

```python
# backend/ai_models/predictor.py
# n_vars: 40 → 60
# 模型容量: n_vars=60, seq_len=60, pred_len=5

class TransformerPredictor:
    def build_model(self, n_vars=60, seq_len=60, pred_len=5):
        ...
```

### 5.4 RL Agent 增强

`TradingEnv` 和 `PortfolioTradingEnv` 的 `feature_dim` 从 40 → 60:

```python
class TradingEnv(gym.Env):
    def __init__(self, df_dict, close_dict=None, feature_dim=60, ...):
        # 状态空间自动扩大: 60 * n_tickers + n_tickers + 1
```

新增信号可直接融入 `rl_agent.predict_signal()` 的 `features` 矩阵，无需修改推理逻辑。

---

## 6. 前端扩展

### 6.1 新增 Dashboard 组件

| 组件 | 路径 | 功能 |
|------|------|------|
| OrderHistory.vue | `src/components/dashboard/` | 订单历史表格，支持按状态/时间筛选 |
| CapitalFlow.vue | `src/components/dashboard/` | 资金流向仪表板 (流入/流出柱状图) |
| FundamentalPanel.vue | `src/components/dashboard/` | 基本面概览面板 (PE/PB/股息率/做空率) |
| ShortInterest.vue | `src/components/dashboard/` | 做空数据监控 (threshold 警报) |
| CorporateCalendar.vue | `src/components/dashboard/` | 财报日历/分红/拆股时间线 |

### 6.2 修改现有组件

- `Dashboard.vue`: 添加 Tab 切换 (实时/订单/基本面/资金流)
- `AccountSummary.vue`: 扩展显示项 (杠杆率、细分资产、期权记录)
- `usePortfolioStore.ts`: 扩展状态管理，新增 orders/capitalFlow/fundamental 状态
- `dataApi.ts`: 新增 API 方法

### 6.3 数据刷新策略

| 数据 | 刷新方式 | 频率 |
|------|---------|------|
| 实时价格 | WebSocket push | ~1s |
| 订单列表 | REST polling | 30s |
| 资金流 | REST polling | 5min |
| 基本面 | REST on-demand | 手动/日更新 |
| 日历事件 | REST on-load | 页面加载时 |

---

## 7. 实施任务列表

### Phase 1: 基础设施 (预估 2-3 天)

| ID | 任务 | 优先级 | 依赖 | 预估工时 |
|----|------|--------|------|----------|
| T1 | 创建 `db.py` 统一数据库模块，含新表 DDL | P0 | 无 | 4h |
| T2 | 创建 `rate_limiter.py` 滑动窗口限流器 | P0 | 无 | 3h |
| T3 | 创建 `sync_state.py` 同步状态管理 | P0 | T1 | 2h |
| T4 | DatabaseMigration: 在 `historical_store._init_db()` 添加全部新表 | P0 | T1 | 2h |

### Phase 2: Tiger API 扩展 (预估 3-4 天)

| ID | 任务 | 优先级 | 依赖 | 预估工时 |
|----|------|--------|------|----------|
| T5 | 扩展 TradeClient 方法: get_orders, get_filled_orders, get_transactions 等 | P0 | 无 | 6h |
| T6 | 扩展 QuoteClient 方法: get_stock_fundamental, get_stock_industry, get_capital_flow 等 | P0 | 无 | 6h |
| T7 | 添加 TigerClient 批量方法 (get_stock_briefs_batch, get_fundamentals_batch) | P0 | T5,T6 | 3h |
| T8 | 创建 `tiger_sync.py` 核心同步协调器 | P0 | T2,T3,T4 | 4h |

### Phase 3: 同步引擎 (预估 2-3 天)

| ID | 任务 | 优先级 | 依赖 | 预估工时 |
|----|------|--------|------|----------|
| T9 | 实现 `tier1_sync.py` (30s 实时同步) | P0 | T8 | 3h |
| T10 | 实现 `tier2_sync.py` (5min 中频同步) | P0 | T8 | 4h |
| T11 | 实现 `tier3_sync.py` (daily 低频同步) | P0 | T8 | 4h |
| T12 | 实现 `alltime_sync.py` (全量初始化) | P0 | T8 | 4h |
| T13 | 集成到 `main.py` lifespan 启动同步服务 | P0 | T9-T12 | 2h |
| T14 | 添加交易时段检测，非交易时段降频 | P1 | T13 | 2h |

### Phase 4: AI 特征增强 (预估 2-3 天)

| ID | 任务 | 优先级 | 依赖 | 预估工时 |
|----|------|--------|------|----------|
| T15 | 创建 `features_fundamental.py` 基本面特征提取器 | P1 | T6 | 3h |
| T16 | 创建 `features_flow.py` 资金流特征提取器 | P1 | T6,T10 | 3h |
| T17 | 扩展 `DataPipeline.FEATURE_COLUMNS` 集成新特征 | P1 | T15,T16 | 3h |
| T18 | 修改 `predictor.py` n_vars 40→60，重新训练验证 | P1 | T17 | 6h |
| T19 | 修改 `rl_agent.py` feature_dim 40→60 | P1 | T17 | 2h |

### Phase 5: API 路由 (预估 1-2 天)

| ID | 任务 | 优先级 | 依赖 | 预估工时 |
|----|------|--------|------|----------|
| T20 | 添加 `/api/data/tiger-orders` 订单查询端点 | P1 | T5,T8 | 2h |
| T21 | 添加 `/api/data/fundamentals` 基本面查询端点 | P1 | T6 | 2h |
| T22 | 添加 `/api/data/capital-flow` 资金流查询端点 | P1 | T6 | 2h |
| T23 | 添加 `/api/data/corporate-events` 公司事件端点 | P1 | T6 | 2h |
| T24 | 扩展 WebSocket 推送 Tiger 实时订单状态更新 | P2 | T5 | 3h |

### Phase 6: 前端扩展 (预估 2-3 天)

| ID | 任务 | 优先级 | 依赖 | 预估工时 |
|----|------|--------|------|----------|
| T25 | 创建 `OrderHistory.vue` 组件 | P1 | T20 | 4h |
| T26 | 创建 `CapitalFlow.vue` 组件 | P1 | T22 | 3h |
| T27 | 创建 `FundamentalPanel.vue` 组件 | P1 | T21 | 3h |
| T28 | 创建 `CorporateCalendar.vue` 组件 | P2 | T23 | 3h |
| T29 | 修改 `Dashboard.vue` 集成新组件 | P1 | T25-T28 | 3h |
| T30 | 扩展 `usePortfolioStore.ts` 状态管理 | P1 | T20-T23 | 2h |

**总预估工时**: 12-18 天 (单人全职)

### 7.1 关键依赖路径

```
T1 → T4 → T3 → T8 → T9 → T13 (Tier 1 可用)
                  → T10 → T14 (Tier 2 可用)
                  → T11 (Tier 3 可用)
                  → T12 (全量初始化可用)

T6 → T15,T16 → T17 → T18,T19 (AI 特征可用)
T6 → T21,T22,T23 (前端 API 可用)
```

---

## 8. 依赖包

### 8.1 Python (pip)

| 包名 | 版本 | 用途 | 状态 |
|------|------|------|------|
| tigeropen | >=3.0.0 | Tiger API SDK | 已有 |
| pandas | >=2.0 | 数据处理 | 已有 |
| numpy | >=1.24 | 数值计算 | 已有 |
| loguru | >=0.7 | 日志 | 已有 |
| fastapi | latest | Web API | 已有 |
| **schedule** | >=1.2 | 定时任务调度 (替代 asyncio.sleep) | **新增** |
| **aiosqlite** | >=0.19 | 异步 SQLite 操作 | **新增** |
| **apscheduler** | >=3.10 | 高级定时任务 (支持 cron) | **新增** |

### 8.2 前端 (npm)

| 包名 | 版本 | 用途 | 状态 |
|------|------|------|------|
| vue | ^3.4 | 前端框架 | 已有 |
| recharts | ^2.10 | 图表 (实际项目用 Vue，需确认) | 已有 |
| pinia | ^2.1 | 状态管理 | 已有 |
| **vue-echarts** | ^6.7 | 高级图表 (资金流/深度图) | **新增** |
| **dayjs** | ^1.11 | 日期处理 (交易日历) | **新增** |

### 8.3 安装命令

```bash
# Python
pip install schedule aiosqlite apscheduler

# 前端
cd frontend && npm install vue-echarts dayjs
```

---

## 9. 风险与注意事项

### 9.1 SQLite 写锁风险

**问题**: SQLite 同时只允许 1 个写入者，多进程/多线程可能导致 `SQLITE_BUSY`。

**缓解**:
1. WAL 模式 (已启用) — 读不阻塞写
2. `busy_timeout=30000` — 30秒超时自动重试
3. 所有写入走单线程队列 (`asyncio.Queue`)，串行化写操作
4. 批量写入使用 SINGLE TRANSACTION
5. Tier 1/2/3 同步错峰执行，避免同时写入
6. 当 Parquet 替代 SQLite 存放大时间序列数据 (OHLCV、tick)

### 9.2 API 限流风险

**问题**: Tiger API 10 calls/min 严格限制，超限可能导致 IP 临时封禁。

**缓解**:
1. 滑动窗口限流器 (`rate_limiter.py`) — 硬限制，宁可延迟不超限
2. 批量合并 (1 call 获取 50 只股票数据)
3. 15秒缓存 (`get_positions`, `get_assets` 已有)
4. 非交易时段自动降频
5. 错误重试使用指数退避 (1s → 2s → 4s → 8s)
6. 仅同步 `data_config.ALL_TICKERS` 范围内的数据，避免无效 API 调用
7. 优先级队列: 实时价格 > 账户数据 > 基本面 > 历史大拉取

### 9.3 数据一致性

**问题**: SQLite 中同一数据多表存储 (如 trades + tiger_orders + tiger_transactions)，可能不一致。

**缓解**:
1. `trades` 表保持本地策略记录，`tiger_orders` 存储 Tiger 实际订单状态
2. 通过 `order_id` 关联两者，但独立维护
3. `portfolio_sync` 使用 Tiger 持仓为单一事实来源
4. 每日盘后对账: `tiger_orders.filled_quantity` vs `tiger_transactions.quantity` sum

### 9.4 磁盘空间

**问题**: SQLite 文件增长 + Parquet 文件累积。

**缓解**:
1. `price_ticks` 保留最近 7 天 (定时清理)
2. `signals` 保留最近 90 天
3. `portfolio_snapshots` 保留全部 (数据量小)
4. Tiger 历史订单仅在初始化时全量拉取，后续增量
5. 预估日增量: ~5MB (含 Parquet)，年增长: ~2GB

### 9.5 数据恢复

**问题**: 同步失败时需要回退。

**缓解**:
1. 同步前备份 `sync_status` 表状态
2. Tier 1/2 失败时使用缓存数据 (已有 15s 缓存)
3. Tier 3 失败时，次日自动重试整日数据
4. 全量初始化支持断点续传 (通过 `sync_status.last_cursor`)

---

## 附录 A: 表大小估算

| 表名 | 单行大小 | 预估行数 | 总大小 |
|------|---------|---------|--------|
| tiger_orders | ~400B | 5,000 | ~2MB |
| tiger_transactions | ~200B | 10,000 | ~2MB |
| stock_metadata | ~500B | 500 | ~250KB |
| capital_flow | ~200B | 40,000 | ~8MB |
| market_calendar | ~150B | 1,000 | ~150KB |
| corporate_events | ~300B | 1,000 | ~300KB |
| sync_status | ~200B | 20 | ~4KB |
| **合计** | | | **~13MB** |

> 现有 DB: ~5MB (trades+signals+price_ticks)，扩增后约 20MB，SQLite 完全可承载。

## 附录 B: 同步时间线

```
00:00 ET (盘前5h)  → Tier 3: 交易日历、财报日历 (2 calls)
04:00 ET (盘前30m) → Tier 3: 基本面更新、行业分类 (4 calls)
09:30 ET (开盘)    → Tier 1 启动 (30s 循环)
                  → Tier 2 启动 (5min 循环)
16:00 ET (收盘)    → Tier 1 降频至 5min
                  → Tier 2 降频至 30min
17:00 ET (盘后)    → Tier 3: 分红/拆股/期权 (4 calls)
20:00 ET (盘后)    → 日终对账、数据清理
```

## 附录 C: 对标行业标准

| 维度 | Tiger 原生限额 | 本方案实现 | 行业对标 |
|------|--------------|-----------|---------|
| 实时价格延迟 | ~1s | ~1s (30s 批处理) | <1s (交易所直连) |
| 基本面更新 | 按需 | 每日 | 每日 |
| 订单追踪 | 按需 | 30s/5min | 实时 |
| 资金流 | 无 | 5min/日 | 实时 (Level 2) |
| AI 特征维度 | 40 | 60 | 100+ (量化基金) |

---

> **文档版本**: v1.0 | **下次评审**: Phase 2 完成后

# Tiger API Full-Data Real-Time Sync System Architecture

> Project: quant-ai-trader | Account: 20874631 | Date: 2026-06-14
> Designer: Architect | Review: team-lead

---

## 1. Database Extension Design

### 1.1 Review of Existing Tables

| Table | Row count | Purpose |
|------|--------|------|
| market_metadata | empty | Parquet metadata index |
| trades | 757 | Trade records |
| signals | 25,940 | Signal history |
| price_ticks | 10,377 | Price cache |
| portfolio_snapshots | 129 | Portfolio snapshots |
| portfolio_account | 1 | Account summary |
| portfolio_positions | 1 | Position snapshot |
| data/daily/*.parquet | ~ | Daily OHLCV |

### 1.2 New Table Design

#### Table 1: `tiger_orders` — Order History

```sql
CREATE TABLE tiger_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE,       -- Tiger global order ID
    parent_id INTEGER,                       -- parent order ID (multi-leg)
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
    outside_rth INTEGER DEFAULT 0,           -- pre-market / after-hours flag
    reason TEXT,                             -- reject reason
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

**Purpose**: Store the full order lifecycle, replacing the local `trades` table's order-tracking capability. Supports strategy review and cost analysis.

**Estimated rows**: ~1,000 (initial) -> ~5,000 / year

#### Table 2: `tiger_transactions` — Fill Details

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

**Purpose**: Fill-level detail for precise P&L attribution and slippage analysis. The existing `trades` table records local strategy decisions; this table records actual Tiger executions.

**Estimated rows**: ~2,000 (initial) -> ~10,000 / year

#### Table 3: `stock_metadata` — Fundamentals / Classification

```sql
CREATE TABLE stock_metadata (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    market TEXT NOT NULL,                    -- US/HK/SG/AU/NZ
    currency TEXT NOT NULL,
    sector TEXT,                             -- GICS sector
    industry TEXT,                           -- industry
    market_cap REAL,                         -- market capitalization
    shares_outstanding REAL,                 -- shares outstanding
    pe_ratio REAL,                           -- P/E
    pb_ratio REAL,                           -- P/B
    eps REAL,                                -- EPS
    dividend_yield REAL,                     -- dividend yield
    beta REAL,                               -- beta
    short_interest REAL,                     -- short interest (%)
    short_ratio REAL,                        -- short ratio (days)
    exchange TEXT,                           -- exchange
    lot_size INTEGER DEFAULT 1,              -- board-lot size
    tick_size REAL,                          -- minimum price increment
    last_updated TEXT NOT NULL,
    source TEXT DEFAULT 'tiger'
);

CREATE INDEX idx_stock_meta_sector ON stock_metadata(sector);
CREATE INDEX idx_stock_meta_market ON stock_metadata(market);
CREATE INDEX idx_stock_meta_mcap ON stock_metadata(market_cap DESC);
```

**Purpose**: Replace the empty `market_metadata` table and store full fundamental data retrieved via Tiger API. Provides fundamental and sector-classification features for AI models.

**Estimated rows**: ~200 (current watchlist) -> ~500 (expanded)

#### Table 4: `capital_flow` — Capital Flow

```sql
CREATE TABLE capital_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,                      -- YYYY-MM-DD
    inflow REAL,                             -- institutional inflow
    outflow REAL,                            -- institutional outflow
    net_flow REAL,                           -- net inflow
    super_large_net REAL,                    -- super-large-order net
    large_net REAL,                          -- large-order net
    medium_net REAL,                         -- medium-order net
    small_net REAL,                          -- small-order net
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, date)
);

CREATE INDEX idx_capital_flow_ticker ON capital_flow(ticker);
CREATE INDEX idx_capital_flow_date ON capital_flow(date);
```

**Purpose**: Capital-flow data as sentiment / flow features for AI models.

**Estimated rows**: ~200 x 20 days = ~4,000

#### Table 5: `market_calendar` — Trading Calendar

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

**Purpose**: Determine trading-session windows and avoid wasting API quota outside market hours.

#### Table 6: `corporate_events` — Corporate Events

```sql
CREATE TABLE corporate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,               -- dividend/split/earnings
    event_date TEXT NOT NULL,
    record_date TEXT,
    pay_date TEXT,
    amount REAL,                             -- dividend amount
    split_ratio TEXT,                        -- split ratio, e.g. "2:1"
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

**Purpose**: Dividends, splits, and earnings calendar to support risk controls and signal filtering.

#### Table 7: `sync_status` — Sync-State Control

```sql
CREATE TABLE sync_status (
    sync_type TEXT PRIMARY KEY,             -- orders/assets/fundamentals/etc
    last_sync_time TEXT,
    last_success_time TEXT,
    last_cursor TEXT,                        -- pagination cursor
    records_synced INTEGER DEFAULT 0,
    status TEXT DEFAULT 'idle',             -- idle/running/error
    error_message TEXT,
    next_scheduled_time TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**Purpose**: Incremental-sync state management; records last sync time and pagination cursor for each data type.

### 1.3 Index Strategy Summary

| Index | Table | Purpose |
|------|-----|------|
| ticker + date | capital_flow, corporate_events | Per-name daily query |
| order_id | tiger_orders, tiger_transactions | Order join queries |
| create_time / event_date | tiger_orders, corporate_events | Time-range queries |
| status | tiger_orders | Filter by status |
| market + date | market_calendar | Trading-day lookup |
| market_cap DESC | stock_metadata | Top-N market-cap sort |

### 1.4 SQLite Optimizations

Keep existing measures and strengthen them:
- `PRAGMA journal_mode=WAL` (already enabled)
- `PRAGMA synchronous=NORMAL` (already enabled)
- `PRAGMA cache_size=-128000` (recommend raising to 128 MB)
- `PRAGMA mmap_size=536870912` (recommend raising to 512 MB)
- Wrap all bulk writes in a transaction (`SINGLE TRANSACTION`)
- Add `busy_timeout=30000` to avoid write-lock contention

---

## 2. Sync Strategy

### 2.1 API Rate-Limit Model

Tiger API is limited to **10 calls/min**. Strategy:

```
Per-minute budget = 10 calls
├── Tier 1 (high frequency): reserve 3 calls/min (live quotes)
├── Tier 2 (medium frequency): reserve 4 calls/min (fundamentals / capital flow)
├── Tier 3 (low frequency): reserve 2 calls/min (calendar / corporate events)
└── Buffer: 1 call/min (retry / burst)
```

**Batch-merge strategy**: Use `get_stock_briefs([symbols])` to fetch many names in one call; 1 call = 50 stocks.

**Effective utilization**: ~3,000 effective data points per day from only 50 actual API calls.

### 2.2 Tier 1 — High-Frequency Sync (30s)

**Trigger**: Every 30 seconds during the trading session

| Data item | API method | Notes |
|--------|----------|------|
| Position live quotes | get_stock_briefs(batch) | 1 call covers all positions; cache already exists |
| Position list | get_positions() | Existing 15s cache; keep |

**Call rate**: 2 calls/min (batched briefs)

### 2.3 Tier 2 — Medium-Frequency Sync (5 min)

**Trigger**: Every 5 minutes during the trading session

| Data item | API method | Purpose | Call count |
|--------|----------|------|----------|
| Capital flow | get_capital_flow() | Institutional-flow tracking | 3 calls (3 batches) |
| Order-book depth | get_depth_quote() | Liquidity assessment | 2 calls (Top 10) |
| Intraday timeline | get_timeline() | Intraday path | 2 calls (active names) |
| Short interest | get_short_interest() | Short-squeeze warning | 1 call |
| Account assets | get_aggregate_assets() | Detailed asset analysis | 1 call |

**Minute budget**: 9 calls, kept within the limit.

### 2.4 Tier 3 — Low-Frequency Sync (Daily)

**Trigger**: Once pre-market and once post-market each day

| Data item | API method | Purpose |
|--------|----------|------|
| Fundamentals | get_stock_fundamental() | PE / PB / ROE refresh |
| Industry classification | get_stock_industry() | Industry membership refresh |
| Industry list | get_industry_list() + get_industry_stocks() | Industry mapping table |
| Trading calendar | get_trading_calendar() | Session planning |
| Market status | get_market_status() | Confirm open status |
| Earnings calendar | get_corporate_earnings_calendar() | Earnings warning |
| Dividend info | get_corporate_dividend() | Ex-dividend / ex-rights |
| Split info | get_corporate_split() | Split / reverse-split handling |
| Option exercise | get_option_exercise_records() | Option-expiry handling |
| Capital distribution | get_capital_distribution() | Flow-structure analysis |

**Call count**: ~12 calls/day (spread across sessions)

### 2.5 All-Time — Initial Full Pull

**Trigger**: Once on first system deploy

| Data item | API method | Expected volume | Expected duration |
|--------|----------|-----------|----------|
| Historical orders | get_orders() paginated | ~1,000 rows | 10–15 min |
| Filled orders | get_filled_orders() | ~800 rows | 5–8 min |
| Cancelled orders | get_cancelled_orders() | ~200 rows | 3–5 min |
| Fill details | get_transactions() | ~2,000 rows | 8–12 min |
| All fundamentals | get_stock_fundamental(batch) | ~40 names | 2–3 min |

**Total duration**: about 30–45 minutes, run outside market hours.

### 2.6 Throttle Controller Design

```python
class TigerRateLimiter:
    """
    Sliding-window rate limiter
    - Window: 60 seconds
    - Limit: 10 calls
    - Strategy: token bucket + priority queue
    """
    def __init__(self, max_calls=10, window=60):
        self.max_calls = max_calls
        self.window = window
        self.call_times: deque[float] = deque()
        self.pending: PriorityQueue[Tuple[int, Callable]] = []  # (priority, callable)

    def can_call(self) -> bool:
        """Return whether a call may be issued."""
        now = time.time()
        while self.call_times and self.call_times[0] < now - self.window:
            self.call_times.popleft()
        return len(self.call_times) < self.max_calls

    def wait_and_call(self, priority: int = 0):
        """Block until a call may be issued."""
        while not self.can_call():
            time.sleep(1.0)
        self.call_times.append(time.time())
```

### 2.7 Session Detection

```python
# Sessions: US 9:30-16:00 ET, Pre 4:00-9:30, After 16:00-20:00
# HK 9:30-16:00 HKT
# SG 9:00-17:00 SGT
# Outside sessions, automatically lower sync frequency -> Tier 2 to 30 min, Tier 3 unchanged
```

---

## 3. File Change List

Ordered by implementation sequence:

### Phase 1: Infrastructure (P0)

| # | Action | File | Notes |
|---|------|------|------|
| 1 | **Create** | `backend/api/db.py` | Unified database module wrapping all DB operations |
| 2 | **Modify** | `backend/data_engine/historical_store.py` | Add new-table initialization, fold into `_init_db()` |
| 3 | **Create** | `backend/services/rate_limiter.py` | Tiger API rate-limit controller |
| 4 | **Create** | `backend/services/sync_state.py` | Sync-state management (read / write `sync_status`) |

### Phase 2: Tiger API Extensions (P0)

| # | Action | File | Notes |
|---|------|------|------|
| 5 | **Modify** | `backend/data_engine/tiger_client.py` | Add Trade API extension methods |
| 6 | **Modify** | `backend/data_engine/tiger_client.py` | Add Quote API extension methods |
| 7 | **Create** | `backend/services/tiger_sync.py` | Core sync orchestrator |

### Phase 3: Sync Engine (P0)

| # | Action | File | Notes |
|---|------|------|------|
| 8 | **Create** | `backend/services/tier1_sync.py` | Tier 1 high-frequency sync (30s) |
| 9 | **Create** | `backend/services/tier2_sync.py` | Tier 2 medium-frequency sync (5 min) |
| 10 | **Create** | `backend/services/tier3_sync.py` | Tier 3 low-frequency sync (daily) |
| 11 | **Create** | `backend/services/alltime_sync.py` | Full initial pull |
| 12 | **Modify** | `backend/main.py` | Integrate sync services into lifespan |

### Phase 4: AI Feature Enrichment (P1)

| # | Action | File | Notes |
|---|------|------|------|
| 13 | **Create** | `backend/data_engine/features_fundamental.py` | Fundamental feature extraction |
| 14 | **Create** | `backend/data_engine/features_flow.py` | Capital-flow feature extraction |
| 15 | **Modify** | `backend/data_engine/data_pipeline.py` | Extend `FEATURE_COLUMNS`; integrate new features |
| 16 | **Modify** | `backend/ai_models/predictor.py` | `n_vars` 40 -> 60 to support the new feature dimension |

### Phase 5: Frontend Extensions (P1)

| # | Action | File | Notes |
|---|------|------|------|
| 17 | **Create** | `src/components/dashboard/OrderHistory.vue` | Order-history table |
| 18 | **Create** | `src/components/dashboard/CapitalFlow.vue` | Capital-flow dashboard |
| 19 | **Create** | `src/components/dashboard/FundamentalPanel.vue` | Fundamentals panel |
| 20 | **Modify** | `src/views/Dashboard.vue` | Integrate new components |
| 21 | **Modify** | `src/stores/usePortfolioStore.ts` | Add order / capital-flow / fundamental state |
| 22 | **Modify** | `src/api/dataApi.ts` | Add new API calls |

### Phase 6: API Routes (P1)

| # | Action | File | Notes |
|---|------|------|------|
| 23 | **Modify** | `backend/api/routes_data.py` | Add Tiger data-query endpoints |
| 24 | **Create** | `backend/api/routes_orders.py` | Order-query endpoints |
| 25 | **Modify** | `backend/config.py` | Add sync configuration keys |

---

## 4. Data Pipeline

### 4.1 End-to-End Data Flow

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
                    │  rate_limiter    │  <- sliding-window throttle 10 calls/min
                    │  (token bucket)  │
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
                    │  tiger_sync    │  <- orchestrator
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
  │  Vue.js      │ │  AI Models   │ │  Trading     │
  │  Dashboard   │ │  Predictor   │ │  Engine      │
  │  Charts      │ │  RL Agent    │ │  Executor    │
  └──────────────┘ └──────────────┘ └──────────────┘
```

### 4.2 Key Data Paths

```
# Live price stream
Tiger get_stock_briefs -> rate_limiter -> tier1_sync -> price_ticks table / memory -> WebSocket -> frontend

# Order-history query
Tiger get_orders -> alltime_sync -> tiger_orders table -> /api/orders/{ticker} -> frontend table

# Fundamentals -> AI features
Tiger get_stock_fundamental -> tier3_sync -> stock_metadata table -> features_fundamental -> DataPipeline -> Predictor/RL
```

---

## 5. AI Feature Enrichment

### 5.1 Current Feature Dimension

Current `DataPipeline.FEATURE_COLUMNS` = **63 dimensions** (see `backend/data_engine/data_pipeline.py:19-62`); the model actually consumes 40 dimensions (`n_vars=40`).

### 5.2 New Features

#### Fundamental Features (Tier 3) — 8 dimensions

| Feature | Source | Description |
|------|------|------|
| pe_ratio_z | stock_metadata | PE z-score within industry |
| pb_ratio_z | stock_metadata | PB z-score within industry |
| eps_growth | stock_metadata | Year-over-year EPS change |
| market_cap_quantile | stock_metadata | Market-cap quantile |
| dividend_yield_norm | stock_metadata | Normalized dividend yield |
| sector_momentum_rank | cross_stock compute | Sector-momentum rank |
| short_interest_ratio | stock_metadata | Short-interest ratio |
| beta_vs_market | stock_metadata | Systematic risk |

#### Capital-Flow Features (Tier 2) — 6 dimensions

| Feature | Source | Description |
|------|------|------|
| net_flow_ratio | capital_flow | Net inflow / market-cap |
| large_order_pct | capital_flow | Large-order share |
| flow_divergence | capital_flow | Flow-price divergence |
| flow_momentum_5d | capital_flow | 5-day flow momentum |
| cumulative_flow_20d | capital_flow | 20-day cumulative net inflow |
| flow_volatility | capital_flow | Flow volatility |

#### Order-Book Features (Tier 2) — 4 dimensions

| Feature | Source | Description |
|------|------|------|
| bid_ask_spread_pct | depth_quote | Bid-ask spread percent |
| depth_imbalance | depth_quote | Order-book imbalance |
| liquidity_score | depth_quote | Liquidity score |
| volume_weighted_depth | depth_quote | Volume-weighted depth |

#### Corporate-Event Features (Tier 3) — 2 dimensions

| Feature | Source | Description |
|------|------|------|
| days_to_earnings | corporate_events | Days until earnings |
| dividend_ex_div_days | corporate_events | Days until ex-dividend |

**New total**: 20 dimensions  
**Expanded total dimension**: 63 + 20 = **83 dimensions** (actual model input 40 -> 60)

### 5.3 Predictor Changes

```python
# backend/ai_models/predictor.py
# n_vars: 40 -> 60
# Model capacity: n_vars=60, seq_len=60, pred_len=5

class TransformerPredictor:
    def build_model(self, n_vars=60, seq_len=60, pred_len=5):
        ...
```

### 5.4 RL Agent Enrichment

`TradingEnv` and `PortfolioTradingEnv` `feature_dim` from 40 -> 60:

```python
class TradingEnv(gym.Env):
    def __init__(self, df_dict, close_dict=None, feature_dim=60, ...):
        # State space expands automatically: 60 * n_tickers + n_tickers + 1
```

New signals can be folded directly into the `features` matrix of `rl_agent.predict_signal()` with no inference-logic change.

---

## 6. Frontend Extensions

### 6.1 New Dashboard Components

| Component | Path | Function |
|------|------|------|
| OrderHistory.vue | `src/components/dashboard/` | Order-history table; filter by status / time |
| CapitalFlow.vue | `src/components/dashboard/` | Capital-flow dashboard (inflow / outflow bars) |
| FundamentalPanel.vue | `src/components/dashboard/` | Fundamentals overview (PE / PB / yield / short interest) |
| ShortInterest.vue | `src/components/dashboard/` | Short-interest monitor (threshold alerts) |
| CorporateCalendar.vue | `src/components/dashboard/` | Earnings / dividend / split timeline |

### 6.2 Changes to Existing Components

- `Dashboard.vue`: add tab switcher (live / orders / fundamentals / capital flow)
- `AccountSummary.vue`: extra display fields (leverage, segmented assets, option records)
- `usePortfolioStore.ts`: extend state with orders / capitalFlow / fundamental
- `dataApi.ts`: add new API methods

### 6.3 Data Refresh Strategy

| Data | Refresh method | Frequency |
|------|---------|------|
| Live prices | WebSocket push | ~1s |
| Order list | REST polling | 30s |
| Capital flow | REST polling | 5 min |
| Fundamentals | REST on-demand | Manual / daily |
| Calendar events | REST on-load | On page load |

---

## 7. Implementation Task List

### Phase 1: Infrastructure (est. 2–3 days)

| ID | Task | Priority | Depends | Est. effort |
|----|------|--------|------|----------|
| T1 | Create `db.py` unified database module including new-table DDL | P0 | none | 4h |
| T2 | Create `rate_limiter.py` sliding-window limiter | P0 | none | 3h |
| T3 | Create `sync_state.py` sync-state management | P0 | T1 | 2h |
| T4 | DatabaseMigration: add all new tables in `historical_store._init_db()` | P0 | T1 | 2h |

### Phase 2: Tiger API Extensions (est. 3–4 days)

| ID | Task | Priority | Depends | Est. effort |
|----|------|--------|------|----------|
| T5 | Extend TradeClient methods: get_orders, get_filled_orders, get_transactions, etc. | P0 | none | 6h |
| T6 | Extend QuoteClient methods: get_stock_fundamental, get_stock_industry, get_capital_flow, etc. | P0 | none | 6h |
| T7 | Add TigerClient batch methods (get_stock_briefs_batch, get_fundamentals_batch) | P0 | T5, T6 | 3h |
| T8 | Create `tiger_sync.py` core sync orchestrator | P0 | T2, T3, T4 | 4h |

### Phase 3: Sync Engine (est. 2–3 days)

| ID | Task | Priority | Depends | Est. effort |
|----|------|--------|------|----------|
| T9 | Implement `tier1_sync.py` (30s live sync) | P0 | T8 | 3h |
| T10 | Implement `tier2_sync.py` (5 min medium-frequency sync) | P0 | T8 | 4h |
| T11 | Implement `tier3_sync.py` (daily low-frequency sync) | P0 | T8 | 4h |
| T12 | Implement `alltime_sync.py` (full initial pull) | P0 | T8 | 4h |
| T13 | Integrate into `main.py` lifespan to start sync services | P0 | T9–T12 | 2h |
| T14 | Add session detection; lower frequency outside market hours | P1 | T13 | 2h |

### Phase 4: AI Feature Enrichment (est. 2–3 days)

| ID | Task | Priority | Depends | Est. effort |
|----|------|--------|------|----------|
| T15 | Create `features_fundamental.py` fundamental feature extractor | P1 | T6 | 3h |
| T16 | Create `features_flow.py` capital-flow feature extractor | P1 | T6, T10 | 3h |
| T17 | Extend `DataPipeline.FEATURE_COLUMNS` to integrate new features | P1 | T15, T16 | 3h |
| T18 | Change `predictor.py` n_vars 40 -> 60; retrain and validate | P1 | T17 | 6h |
| T19 | Change `rl_agent.py` feature_dim 40 -> 60 | P1 | T17 | 2h |

### Phase 5: API Routes (est. 1–2 days)

| ID | Task | Priority | Depends | Est. effort |
|----|------|--------|------|----------|
| T20 | Add `/api/data/tiger-orders` order-query endpoint | P1 | T5, T8 | 2h |
| T21 | Add `/api/data/fundamentals` fundamentals endpoint | P1 | T6 | 2h |
| T22 | Add `/api/data/capital-flow` capital-flow endpoint | P1 | T6 | 2h |
| T23 | Add `/api/data/corporate-events` corporate-events endpoint | P1 | T6 | 2h |
| T24 | Extend WebSocket to push Tiger live order-status updates | P2 | T5 | 3h |

### Phase 6: Frontend Extensions (est. 2–3 days)

| ID | Task | Priority | Depends | Est. effort |
|----|------|--------|------|----------|
| T25 | Create `OrderHistory.vue` component | P1 | T20 | 4h |
| T26 | Create `CapitalFlow.vue` component | P1 | T22 | 3h |
| T27 | Create `FundamentalPanel.vue` component | P1 | T21 | 3h |
| T28 | Create `CorporateCalendar.vue` component | P2 | T23 | 3h |
| T29 | Modify `Dashboard.vue` to integrate new components | P1 | T25–T28 | 3h |
| T30 | Extend `usePortfolioStore.ts` state management | P1 | T20–T23 | 2h |

**Total estimated effort**: 12–18 days (one full-time engineer)

### 7.1 Critical Dependency Path

```
T1 -> T4 -> T3 -> T8 -> T9 -> T13 (Tier 1 available)
                  -> T10 -> T14 (Tier 2 available)
                  -> T11 (Tier 3 available)
                  -> T12 (full initial pull available)

T6 -> T15, T16 -> T17 -> T18, T19 (AI features available)
T6 -> T21, T22, T23 (frontend APIs available)
```

---

## 8. Dependency Packages

### 8.1 Python (pip)

| Package | Version | Purpose | Status |
|------|------|------|------|
| tigeropen | >=3.0.0 | Tiger API SDK | existing |
| pandas | >=2.0 | Data processing | existing |
| numpy | >=1.24 | Numerics | existing |
| loguru | >=0.7 | Logging | existing |
| fastapi | latest | Web API | existing |
| **schedule** | >=1.2 | Scheduled jobs (replace asyncio.sleep) | **new** |
| **aiosqlite** | >=0.19 | Async SQLite | **new** |
| **apscheduler** | >=3.10 | Advanced scheduling (cron) | **new** |

### 8.2 Frontend (npm)

| Package | Version | Purpose | Status |
|------|------|------|------|
| vue | ^3.4 | Frontend framework | existing |
| recharts | ^2.10 | Charts (project is Vue; confirm usage) | existing |
| pinia | ^2.1 | State management | existing |
| **vue-echarts** | ^6.7 | Advanced charts (flow / depth) | **new** |
| **dayjs** | ^1.11 | Date handling (trading calendar) | **new** |

### 8.3 Install Commands

```bash
# Python
pip install schedule aiosqlite apscheduler

# Frontend
cd frontend && npm install vue-echarts dayjs
```

---

## 9. Risks and Caveats

### 9.1 SQLite Write-Lock Risk

**Issue**: SQLite allows only one writer at a time; multi-process / multi-thread use can raise `SQLITE_BUSY`.

**Mitigation**:
1. WAL mode (already enabled) — readers do not block writers
2. `busy_timeout=30000` — automatic retry with a 30-second timeout
3. All writes go through a single-thread queue (`asyncio.Queue`) to serialize writes
4. Bulk writes use `SINGLE TRANSACTION`
5. Stagger Tier 1 / 2 / 3 sync so they do not write simultaneously
6. Use Parquet instead of SQLite for large time-series (OHLCV, ticks)

### 9.2 API Rate-Limit Risk

**Issue**: Tiger API's 10 calls/min limit is strict; exceeding it can cause temporary IP bans.

**Mitigation**:
1. Sliding-window limiter (`rate_limiter.py`) — hard cap; prefer delay over overshoot
2. Batch merge (1 call fetches 50 stocks)
3. 15-second cache (`get_positions`, `get_assets` already present)
4. Automatically lower frequency outside market hours
5. Retries use exponential backoff (1s -> 2s -> 4s -> 8s)
6. Sync only names in `data_config.ALL_TICKERS` to avoid wasted API calls
7. Priority queue: live prices > account data > fundamentals > large historical pulls

### 9.3 Data Consistency

**Issue**: The same data can live in multiple SQLite tables (e.g. `trades` + `tiger_orders` + `tiger_transactions`) and drift.

**Mitigation**:
1. Keep `trades` as the local strategy record; store actual Tiger order state in `tiger_orders`
2. Join via `order_id` but maintain independently
3. `portfolio_sync` uses Tiger positions as the single source of truth
4. Daily post-market reconciliation: `tiger_orders.filled_quantity` vs. sum of `tiger_transactions.quantity`

### 9.4 Disk Space

**Issue**: SQLite file growth + accumulating Parquet files.

**Mitigation**:
1. Keep `price_ticks` for the last 7 days (scheduled cleanup)
2. Keep `signals` for the last 90 days
3. Keep all `portfolio_snapshots` (small volume)
4. Full Tiger historical-order pull only at init; incremental thereafter
5. Estimated daily increment: ~5 MB (including Parquet); annual growth: ~2 GB

### 9.5 Data Recovery

**Issue**: Sync failures need rollback.

**Mitigation**:
1. Back up `sync_status` table state before each sync
2. On Tier 1 / 2 failure, use cached data (existing 15s cache)
3. On Tier 3 failure, automatically retry the full day's data the next day
4. Full initial pull supports resume via `sync_status.last_cursor`

---

## Appendix A: Table-Size Estimates

| Table | Bytes / row | Estimated rows | Total size |
|------|---------|---------|--------|
| tiger_orders | ~400B | 5,000 | ~2 MB |
| tiger_transactions | ~200B | 10,000 | ~2 MB |
| stock_metadata | ~500B | 500 | ~250 KB |
| capital_flow | ~200B | 40,000 | ~8 MB |
| market_calendar | ~150B | 1,000 | ~150 KB |
| corporate_events | ~300B | 1,000 | ~300 KB |
| sync_status | ~200B | 20 | ~4 KB |
| **Total** | | | **~13 MB** |

> Existing DB: ~5 MB (trades + signals + price_ticks). After expansion ~20 MB, well within SQLite capacity.

## Appendix B: Sync Timeline

```
00:00 ET (5h pre-market)  -> Tier 3: trading calendar, earnings calendar (2 calls)
04:00 ET (30m pre-open)   -> Tier 3: fundamentals refresh, industry classification (4 calls)
09:30 ET (open)           -> Tier 1 starts (30s loop)
                          -> Tier 2 starts (5 min loop)
16:00 ET (close)          -> Tier 1 down to 5 min
                          -> Tier 2 down to 30 min
17:00 ET (after hours)    -> Tier 3: dividends / splits / options (4 calls)
20:00 ET (after hours)    -> end-of-day reconciliation, data cleanup
```

## Appendix C: Industry Benchmarks

| Dimension | Tiger native limit | This design | Industry benchmark |
|------|--------------|-----------|---------|
| Live price latency | ~1s | ~1s (30s batch) | <1s (exchange direct) |
| Fundamentals refresh | on demand | daily | daily |
| Order tracking | on demand | 30s / 5 min | real time |
| Capital flow | none | 5 min / daily | real time (Level 2) |
| AI feature dimension | 40 | 60 | 100+ (quant funds) |

---

> **Document version**: v1.0 | **Next review**: after Phase 2 completes

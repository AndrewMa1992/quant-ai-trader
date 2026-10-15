# Real-Time Trading Signal Panel — System Design

> Architect: Gao Jianyuan
> Date: 2026-05-16
> Project: quant-ai-trader

---

## 1. Implementation Plan + Framework Selection

### Overall strategy: incremental development, no rewrite of existing code

- **Backend** Python 3.11+ / FastAPI — keep the current framework; add routes and modules
- **Frontend** Vue 3 (Composition API) + Pinia + ECharts — keep the current framework; add components
- **Communication** REST API (POST / GET) + passive WebSocket push (reuse existing `/ws`)
- **State management** Frontend Pinia (`portfolioStore`) and backend in-memory `SignalHistory`

### Incremental principles

| Principle | Description |
|------|------|
| Do not change existing endpoints | `GET /api/analysis/latest-signals`, `GET /api/analysis/strategy-status` stay as-is |
| Do not change existing models | `TradingStrategy`, `SignalEnsemble`, etc. keep their signatures |
| Loosely coupled additions | New `SignalHistory` module is self-contained and does not invade the existing loop |
| Frontend componentization | The signal-card skeleton inside `Dashboard.vue` stays; add a standalone `SignalPanel.vue` |

---

## 2. File List and Relative Paths

### Backend (3 new files, 2 modified files)

```
- [mod]  backend/main.py                  # lifespan initializes SignalHistory, injects routes_analysis
- [new]  backend/api/models/signal.py     # Pydantic request / response models
- [mod]  backend/api/routes_analysis.py   # add POST /api/analysis/run-analysis, GET/POST signal_history
- [new]  backend/services/signal_history.py  # SignalHistory in-memory store + history management
- [new]  backend/services/__init__.py     # services package init
```

### Frontend (3 new files, 2 modified files)

```
- [new]  frontend/src/components/SignalPanel.vue      # signal-panel main component
- [new]  frontend/src/components/SignalCard.vue        # single signal-card component
- [new]  frontend/src/components/SignalTrendChart.vue  # sparkline trend chart component
- [mod]  frontend/src/views/Dashboard.vue              # mount SignalPanel; replace the old signal region
- [mod]  frontend/src/stores/portfolio.js              # new signals actions: runAnalysis, fetchSignalHistory
```

---

## 3. Core Data Structures / Interfaces

### 3.1 Pydantic Models (`backend/api/models/signal.py`)

```python
# --- Request ---
class RunAnalysisRequest(BaseModel):
    tickers: Optional[List[str]] = None  # None = all

# --- Model-contribution detail ---
class ModelDetail(BaseModel):
    score: float
    weight: float
    confidence: float

class SignalCard(BaseModel):
    ticker: str
    decision: str              # "buy" | "sell" | "hold"
    strength: float            # 0.0 ~ 1.0
    confidence: float          # 0.0 ~ 1.0
    position_size: float       # 0.0 ~ 1.0
    ensemble_score: float      # raw fused score
    details: Dict[str, ModelDetail]  # model-contribution detail
    timestamp: str             # ISO time

class RunAnalysisResponse(BaseModel):
    status: str                # "ok" | "partial"
    total: int
    timestamp: str
    signals: Dict[str, SignalCard]

class SignalHistoryEntry(BaseModel):
    cycle: int
    decision: str
    strength: float
    confidence: float
    timestamp: str

class SignalHistoryResponse(BaseModel):
    ticker: str
    history: List[SignalHistoryEntry]
```

### 3.2 SignalHistory In-Memory Store Interface (`backend/services/signal_history.py`)

```python
class SignalHistory:
    """Keep the last MAX_HISTORY signal cycles per ticker."""

    MAX_HISTORY = 20

    def __init__(self):
        self._store: Dict[str, List[Dict]] = {}  # ticker -> [entry, ...]

    def append(self, ticker: str, signal: Dict) -> None
    def get_history(self, ticker: str, limit: int = 20) -> List[Dict]
    def get_all_latest(self) -> Dict[str, Dict]
    def get_all_history(self, limit: int = 20) -> Dict[str, List[Dict]]
    def clear(self) -> None
    def count(self) -> int
```

### 3.3 Frontend SignalPanel.vue Props / Events

```javascript
// Props
defineProps({
  signals: { type: Object, required: true },        // { ticker: { decision, strength, confidence, position_size, details } }
  signalHistory: { type: Object, default: () => ({}) },  // { ticker: [ { cycle, decision, strength, confidence, timestamp }, ... ] }
  loading: { type: Boolean, default: false },
  lastUpdated: { type: String, default: '' },
  autoRefresh: { type: Boolean, default: false },
})

// Events (defineEmits)
emit('run-analysis')       // click "Run analysis"
emit('toggle-autorefresh') // toggle auto-refresh
emit('filter-change', filterValue)  // filter: all | buy | sell | hold
```

---

## 4. Program Call Flow (Sequence)

### 4.1 Click the "Run analysis" Button

```
User Click [Run analysis]
   │
   ▼
SignalPanel.vue ──emit('run-analysis')──▶ Dashboard.vue
   │                                          │
   │                                    portfolioStore.runAnalysis()
   │                                          │
   │                                     POST /api/analysis/run-analysis
   │                                          │
   │                                     routes_analysis.run_analysis()
   │                                          │
   │                                     ┌────┴────────────────────┐
   │                                     │ 1. Get all / specified tickers │
   │                                     │ 2. build_data_dict()    │
   │                                     │ 3. market_data fetch prices │
   │                                     │ 4. strategy.analyze_and │
   │                                     │    _trade(tickers, data,│
   │                                     │     prices)             │
   │                                     │      |- Transformer predict│
   │                                     │      |- RL Agent infer  │
   │                                     │      |- Sentiment analysis │
   │                                     │      |- Technical signal │
   │                                     │      |- ensemble.fuse   │
   │                                     │ 5. SignalHistory.append │
   │                                     │     (write each ticker) │
   │                                     └────┬────────────────────┘
   │                                          │
   │                                     ◀───┘
   │                                   RunAnalysisResponse
   │                                          │
   │◀──────────────────────────────────────────┘
   │
   ▼
SignalPanel.vue updates signal cards + sparkline
```

### 4.2 Auto-Poll (30s Interval)

```
SignalPanel.vue (onMounted -> setInterval 30s)
   │
   ├── call: portfolioStore.fetchLatestSignals()
   │         │
   │      GET /api/analysis/latest-signals
   │         │
   │      routes_analysis.get_latest_signals()
   │         └─ return strategy.last_signals
   │
   ├── call: portfolioStore.fetchSignalHistory()
   │         │
   │      GET /api/analysis/signal-history
   │         │
   │      routes_analysis.get_signal_history()
   │         └─ return signal_history.get_all_history()
   │
   └── Update signal cards (do not trigger model inference)
```

### 4.3 Passive WebSocket Push (Existing Mechanism)

```
strategy_engine scheduled analysis loop
   │
   |- Same as 4.1 steps 1-5
   │
   |- _emit_analysis(results) ──▶ handle_analysis_result
   │                                   │
   │                              broadcast via /ws
   │                                   │
   │                              Dashboard.vue WebSocket onmessage
   │                                   │
   │                              portfolioStore.updateSignals()
   │                                   │
   │                              SignalPanel auto-refresh
   │
   └─ SignalHistory.append() (same as above)
```

---

## 5. Task List (Implementation Order)

| # | Depends | Description | Est. effort |
|------|------|------|----------|
| 1 | [] | Backend: create `backend/api/models/signal.py` — Pydantic request / response models | 0.5h |
| 2 | [] | Backend: create `backend/services/signal_history.py` — in-memory history store | 0.5h |
| 3 | [1,2] | Backend: modify `routes_analysis.py` — add POST `/run-analysis` and GET `/signal-history` | 2h |
| 4 | [3] | Backend: modify `main.py` — lifespan initializes SignalHistory and injects routes | 0.3h |
| 5 | [] | Frontend: create `components/SignalCard.vue` — single signal card (decision badge + strength bar + confidence + size + expand region) | 1.5h |
| 6 | [] | Frontend: create `components/SignalTrendChart.vue` — ECharts sparkline | 1h |
| 7 | [5,6] | Frontend: create `components/SignalPanel.vue` — top action bar + filter tabs + card list + trend chart + auto-poll | 2h |
| 8 | [7] | Frontend: modify `Dashboard.vue` — mount SignalPanel in place of the old signal region | 0.5h |
| 9 | [] | Frontend: modify `stores/portfolio.js` — add `runAnalysis()`, `fetchSignalHistory()` actions | 0.5h |
| 10 | [all] | Front/back joint debug + edge-case tests (empty signals / model not ready / network error) | 1.5h |

**Total estimate: ~10.3 hours**

### Implementation notes

- Tasks 1–4 can be done by a backend developer; tasks 5–9 by a frontend developer; they can overlap
- Task 10 needs front/back collaboration
- Frontend tasks 5 and 6 can be developed in parallel

---

## 6. Dependency Package List

### Backend

No new dependencies. Existing `fastapi`, `pydantic`, `numpy`, `loguru` cover this work.

### Frontend

No new dependencies. Existing `echarts`, `pinia`, `axios`, `vue` cover this work.
`package.json` already has `echarts ^5.4.0`; the sparkline uses it directly.

---

## 7. Shared Knowledge (Cross-File Conventions)

### Field-naming conventions

- Backend: all-lowercase snake_case (e.g. `position_size`, `ensemble_score`, `model_detail`)
- Frontend: follow Vue convention; templates access the same names
- API paths: `/api/analysis/{action}`, all-lowercase kebab-case

### Decision color conventions

| Decision | Color | CSS variable / class |
|------|------|------------------|
| buy | green (#22c55e) | `.badge-buy` / `var(--signal-buy)` |
| sell | red (#ef4444) | `.badge-sell` / `var(--signal-sell)` |
| hold | gray (#6b7280) | `.badge-hold` / `var(--signal-hold)` |

### Strength progress-bar thresholds

| Strength range | Color intensity | UI presentation |
|----------|----------|---------|
| >= 0.6 | deep | dark green / dark red |
| 0.3 ~ 0.6 | mid | mid green / mid red |
| < 0.3 | light | light green / light red / light gray |

### Frontend component-interface conventions

- `SignalPanel.vue` receives a `signals` object matching `portfolioStore.signals` (`{ ticker: { decision, strength, confidence, position_size, details } }`)
- `SignalCard.vue` emits an `expand` event to expand / collapse model-contribution detail
- Sparklines always use 20 data points; x-axis is cycle index; y-axis is strength

### Error-handling conventions

- Backend: all APIs return `{"status": "error", "message": "..."}` on error
- Backend: empty signal lists return `{"status": "ok", "signals": {}, "total": 0}`, not an error
- Frontend: `loading` is owned by `SignalPanel.vue`; on request failure show an error toast rather than a blank panel

---

## 8. Open Items

| # | Item | Recommended decision |
|---|------|----------|
| 1 | Should the `run-analysis` endpoint run asynchronously (long-running)? | Prefer sync (few tickers, fast inference). If ticker count later exceeds 30, switch to async + polling |
| 2 | Should auto-refresh also write SignalHistory? | No: polling only reads `last_signals` and does not trigger inference; only `run-analysis` writes history |
| 3 | Should WebSocket push results share the `run-analysis` response format? | Yes: WebSocket message `{type: "analysis_result", data: RunAnalysisResponse}` |
| 4 | Persist SignalHistory to a database? | Not in this P0 / P1; in-memory only. P2 can consider SQLite |
| 5 | Does the sparkline show all tickers or only the selected ticker? | Each SignalCard independently shows that ticker's history |

# PRD: Real-Time Trading Signal Panel

| Item | Content |
|------|------|
| Product | quant-ai-trader — quantitative AI US / HK equity trading system |
| Version | v1.0 |
| Status | Pending review |

---

## 1. Product Goal

**In one sentence**: Give the AI trading system a real-time, visual signal view so users can see each name's buy / sell / hold call, multi-model consensus, and position recommendation at a glance.

---

## 2. User Stories

- **US-1**: As a quantitative trader, I want to trigger the full analysis pipeline with one click and immediately see buy / sell / hold signals for all 18 holdings, so I can quickly understand the current market view.
- **US-2**: As a risk officer, I want to inspect the model breakdown behind each signal (Transformer / RL / Sentiment / Technical scores and confidences), so I can judge whether the signal is reliable.
- **US-3**: As a strategy researcher, I want to observe how signals change over time, to see whether model judgment is stable and how signal strength evolves.

---

## 3. Requirements List

### P0 — Core Features

| ID | Requirement | Description |
|----|------|------|
| P0-1 | **One-click run analysis** | The panel provides a "Run analysis" button that calls the backend to trigger the full flow: fetch live data -> run each model -> fuse signals -> return results. Must cover all 18 names. |
| P0-2 | **Signal-card display** | One signal card per name showing: ticker, decision (buy / sell / hold, color-coded badge), signal strength (0–100%), confidence (0–100%), recommended position (0–100%). |
| P0-3 | **Model-contribution breakdown** | Each signal card can expand to show per-model contributions: Transformer (direction + confidence), RL Agent (mean action), Sentiment (signal + strength), Technical (indicator + strength). Display weights and the fused `ensemble_score`. |
| P0-4 | **Queue / loading state** | After clicking "Run analysis", show a loading animation; while the backend runs, the frontend polls `/api/analysis/strategy-status` or `/api/analysis/latest-signals` until analysis completes or times out. |

### P1 — Important Features

| ID | Requirement | Description |
|----|------|------|
| P1-1 | **Signal history trend** | For each signal, record the last N cycles (e.g. 20) of decision / strength changes, shown as a sparkline of strength and a decision-change timeline. |
| P1-2 | **Automatic timed refresh** | The panel supports auto-refresh (default poll every 30 seconds). Users can toggle it or change the interval. Polling only fetches the latest signals; it does not re-trigger full analysis. |
| P1-3 | **Signal-strength visualization** | Show strength as a progress bar or gauge rather than a raw number. Buy deepens green; sell deepens red; hold is gray. |
| P1-4 | **Signal filter and sort** | Filter by decision type (buy / sell / hold) and sort by strength so users can focus on high-confidence signals. |

---

## 4. UI Sketch

### Layout (Signal Panel region)

```
┌─────────────────────────────────────────────────────────────┐
│  [Run analysis] [Auto-refresh: 30s ▼]  Last update: 14:32:05 │
├─────────────────────────────────────────────────────────────┤
│ All(18) | Buy(5) | Sell(3) | Hold(10)   [Sort by strength ▼] │
├─────────────────────────────────────────────────────────────┤
│ ┌─── Signal card ───────────────────────────────────────┐   │
│ │ AAPL    [BUY]   Strength ████████░░ 80%  Conf 75%     │   │
│ │                   Suggested size: 15%                 │   │
│ │ ─── Model contribution ────────────────────────────── │   │
│ │  Transformer: ↗ up  conf 82%   weight 0.30            │   │
│ │  RL Agent:    buy action 0.42  weight 0.25            │   │
│ │  Sentiment:   bullish  strength 0.65   weight 0.25    │   │
│ │  Technical:   buy  strength 0.55   weight 0.20        │   │
│ │  └─ Ensemble Score: 0.62 -> strong consensus          │   │
│ │                                      [Trend ▸]        │   │
│ └────────────────────────────────────────────────────────┘   │
│ ┌─── Signal card ───────────────────────────────────────┐   │
│ │ TSLA    [SELL]  Strength ██████░░░░ 55%  Conf 60%     │   │
│ │ ...                                                   │   │
│ └────────────────────────────────────────────────────────┘   │
│ ... more cards ...                                           │
│                                                              │
│ ┌─── Signal trend detail (expanded) ────────────────────┐   │
│ │   [Line chart: signal strength vs time]               │   │
│ │   [Color dots: green buy, red sell, gray hold]        │   │
│ └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Key design points**:

- Signal cards reuse the current Dashboard.vue right-side "Trading signals" card style, with richer information
- New top action bar: Run analysis button + auto-refresh toggle
- Filter tab row: quickly switch buy / sell / hold / all
- Each card collapses model-contribution detail by default; click to expand
- The trend button opens a drawer or overlay with the historical signal line chart
- Strength progress bar: buy green, sell red, hold gray

---

## 5. Open Questions

| # | Question | Recommended decision |
|---|------|----------|
| Q1 | **Which backend endpoint does the Run analysis button call?** | Add POST `/api/analysis/run-analysis` to trigger the full flow (data fetch -> model inference -> signal fusion) and return complete results for all 18 signals. |
| Q2 | **Are model-contribution `details` fields aligned?** | Current `ensemble.py` `details` includes score / weight / confidence; the frontend should consume them directly. The frontend must map score (-1 to 1) to a visual "direction + strength". |
| Q3 | **Where is signal history stored?** | Add a backend `SignalHistory` class keyed by ticker, keeping the last 20 signal snapshots. Reuse the existing `last_signals` structure. No extra database. |
| Q4 | **Which endpoint for auto-refresh polling?** | Reuse GET `/api/analysis/latest-signals`. Note it currently depends on `strategy.last_signals` (populated only after an analysis cycle). When no analysis has run for a long time, return "no signals" rather than an error. |
| Q5 | **Where is the complete list of 18 names?** | Dashboard has `usTickers` and `hkTickers`; extract them as shared config or expose them via backend `/api/config/tickers`. |
| Q6 | **Color thresholds for the strength progress bar?** | strength >= 0.6 dark, 0.3–0.6 mid, < 0.3 light. Buy uses greens, sell uses reds, hold is uniform gray. |
| Q7 | **Should users be able to override signals manually?** | Not in this release. Users can view signals only; they cannot edit them. |

---

## 6. Technical Implementation Notes

| Layer | Recommendation |
|------|------|
| Backend | Add `POST /api/analysis/run-analysis`; iterate `TICKER_LIST` -> DataPipeline features -> per-model inference -> SignalEnsemble.fuse_signals -> MemorySignalStore -> return all results |
| Frontend | Extract the signal panel into `SignalPanel.vue` from Dashboard. Reuse existing `portfolioStore.updateSignals`. Add polling and a trend chart (ECharts mini chart). |
| Data flow | run-analysis (one-shot) -> return full signals -> frontend render; auto-refresh (interval poll) -> GET /api/analysis/latest-signals -> incremental UI update |

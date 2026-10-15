# Product Requirement Document — Quant AI Trader v2.1

**Author**: Alice (Product Manager)  
**Date**: 2025-06-08  
**Project**: quant-ai-trader  
**Tech Stack**: FastAPI (8001) + Vue 3 + Vite (5180) + PatchTST Transformer + PPO RL + FinBERT + Ensemble  
**Live Account**: #20874631 | Current NAV: ~$2,569 (from $1M initial)

---

## 1. Project information

| Field | Value |
|---|---|
| **Language** | Chinese |
| **Programming Language** | Vite + Vue 3 + TypeScript + Tailwind CSS |
| **Project Name** | `quant_ai_trader` |
| **Original requirements** | Fix all errors → rewrite the frontend in Xiaomi style → enable live trading → refactor the code to top-tier quant fund standards → train neural networks |

---

## 2. Product definition

### 2.1 Product Goals

| # | Goal | KPI | Target |
|---|---|---|---|
| G1 | **Zero-error system operation** | Count of critical errors (P0/P1) to zero; Hong Kong stock data fetch success rate | 100% (44/44), currently 4/44 |
| G2 | **Frontend brand upgrade** | Xiaomi design language consistency score; page load time | Lighthouse ≥ 90; FCP < 1.5s |
| G3 | **Safe live-trading launch** | Maximum single-day loss; circuit-breaker trigger latency | Single-day loss ≤ 5%; circuit breaker < 1 second |
| G4 | **Quant-fund-grade code quality** | Test coverage; architectural consistency | Core modules ≥ 80%; eliminate monolith/microservice duality |
| G5 | **Usable model training** | Transformer training without crashes; RL inference latency | Training success rate 100%; single inference < 100ms |

### 2.2 User Stories

#### Trader
- **US-1**: As a trader, I want to see at a glance on the Xiaomi-style Dashboard the **portfolio NAV / daily P&L / drawdown**, so that I can complete a status assessment in 30 seconds before the market open.
- **US-2**: As a trader, I want **automatic flatten + desktop notification + email alert** when the risk circuit breaker fires, so that a catastrophic loss from $1M → $2.5K cannot happen again.
- **US-3**: As a trader, I want **Hong Kong market data fetched as reliably as US market data**, so that cross-market strategy signals do not fail due to missing data.

#### Developer
- **US-4**: As a developer, I want a **unified TypeScript frontend stack** (no mixed .js/.ts), so that IDE IntelliSense and type checking work fully.
- **US-5**: As a developer, I want a **unified microservice architecture** (eliminate the backend/ monolith vs services/ duality), so that each module can be deployed, tested, and scaled independently.
- **US-6**: As a developer, I want the **RL agent to auto-detect and use GPU (CUDA/MPS)**, so that training speed improves 5-10x.

#### Risk Officer
- **US-7**: As a risk officer, I want a **portfolio-level circuit breaker** (automatically flatten all positions and halt trading when same-day loss > 5%), so that principal is hard-protected in extreme markets.

---

## 3. Technical specification

### 3.1 Requirements Pool

#### P0 — Blocks release; must fix

| ID | Issue | Impact | Acceptance criteria |
|---|---|---|---|
| P0-1 | **Hong Kong ticker routing error**: numeric HK tickers (00700) without the .HK suffix are queried by yfinance as US stocks | 40/44 HK data fetches fail; cross-market strategies are paralyzed | `GET /api/data/history/00700.HK` returns a valid DataFrame |
| P0-2 | **Portfolio has no circuit breaker**: risk control only rejects new entries and does not trigger portfolio-level auto-flatten | $1M → $2,569, 99.7% loss | When same-day loss ≥ 5%, trigger circuit breaker: (1) flatten all (2) halt new trades (3) send alerts |
| P0-3 | **Frontend JS/TS migration leftovers**: main.ts/main.js, router/index.ts/index.js, vite.config.ts/vite.config.js coexist | Build non-determinism; editor type inference is confused | Keep only .ts files; delete all redundant .js files |
| P0-4 | **lint script references an undeclared dependency**: package.json lint script references eslint, but eslint is not in devDependencies | `npm run lint` fails | eslint is correctly installed and lint passes |

#### P1 — Affects core experience; fix within the sprint

| ID | Issue | Impact | Acceptance criteria |
|---|---|---|---|
| P1-1 | **RL PPO forced to CPU**: rl_agent.py L124 hardcodes `device="cpu"` | GPU wasted; training 5-10x slower | `device` auto-detects CUDA/MPS/CPU |
| P1-2 | **RL predict_signal unstable**: single-stock inference requires a virtual ticker; dimension matching depends on heuristics | Unreliable inference | Explicit single/multi-stock inference paths; unit-test coverage |
| P1-3 | **Transformer training crash**: `numpy.array has no attribute 'empty'` | Training pipeline unusable | Training completes an epoch without error |
| P1-4 | **Watchdog repeatedly fails to restart the backend**: boot_launcher/boot_guard stability is insufficient | Unattended system may stay offline for long periods | Watchdog uptime ≥ 99% |
| P1-5 | **Triple dependency configs coexist**: pyproject.toml + requirements.txt + backend/requirements.txt | Dependency conflict risk | Unify on pyproject.toml; delete the rest |
| P1-6 | **33% of Views exist in old and new versions**: Dashboard.vue vs DashboardView.vue and 7 other pairs | Maintenance chaos; router targets are inconsistent | Keep one component per page; delete redundant versions |

#### P2 — Quality improvements; can be deferred

| ID | Issue | Impact | Acceptance criteria |
|---|---|---|---|
| P2-1 | **Ensemble double normalization**: `_adjust_weights()` divides by total then by ws (redundant) | Minor performance waste | Normalize once |
| P2-2 | **Dual architecture: monolith (backend/) and microservices (services/)** | High maintenance cost | Unify on services/ microservices; backend/ retains only api_gateway |
| P2-3 | **v1 backend has no tests** | High refactor risk | Core modules (risk_manager, ensemble, portfolio) test coverage ≥ 80% |
| P2-4 | **Frontend dependency cleanup**: delete unused components (SignalCard, SignalPanel, old .js stores) | Bundle size + maintenance cost | No unused imports; build has no dead-code warnings |

### 3.2 UI Design Draft — Xiaomi design language

#### Design principles
- **Minimal white background**: `#FAFAFA` / `#FFFFFF` as primary; very light card shadows
- **High contrast**: body text `#1A1A1A`, secondary text `#666666`, WCAG AA
- **Orange accents**: `#FF6700` (Xiaomi orange) for CTA buttons, key metric highlights, selected state
- **Gray scale**: `#F5F5F5` (card background), `#EEEEEE` (dividers), `#E0E0E0` (borders)
- **Smooth animation**: page transitions use `cubic-bezier(0.4, 0, 0.2, 1)` easing, duration ≤ 300ms

#### Layout structure
```
┌──────────────────────────────────────────┐
│  Sidebar (240px)        │  Main Content  │
│  ┌──────────────┐       │                │
│  │  Logo / Icon │       │  ┌──────────┐  │
│  │  Dashboard   │       │  │ Metrics  │  │
│  │  Factors     │       │  │ Row      │  │
│  │  Models      │       │  ├──────────┤  │
│  │  Risk        │       │  │ Chart    │  │
│  │  Portfolio   │       │  │ Area     │  │
│  │  Backtest    │       │  ├──────────┤  │
│  │  Execution   │       │  │ Table    │  │
│  └──────────────┘       │  └──────────┘  │
│                         │                │
└──────────────────────────────────────────┘
```

#### Core page design elements
| Page | Key elements |
|---|---|
| **Dashboard** | Top KPI card row (NAV / daily P&L / drawdown / Sharpe ratio), each card with a mini sparkline |
| **Risk Dashboard** | Circuit-breaker status indicator (green/yellow/red), real-time drawdown gauge, VaR heatmap |
| **Model Center** | Model training progress bar (Xiaomi orange), per-model PnL attribution waterfall |
| **Portfolio** | Position list with color coding (green up / red down, desaturated to Xiaomi gray tones) |
| **Execution** | Trade-log timeline, real-time order status cards |

#### Technical implementation
- **Tailwind CSS** custom theme: extend `tailwind.config.js` with the Xiaomi palette
- **Component library**: Tailwind + custom components only; do not introduce heavy UI libraries such as Element Plus / Ant Design (keep it lean)
- **Fonts**: system default CJK fonts (PingFang SC / Microsoft YaHei); Inter for English

---

## 4. Open questions

| # | Question | Options | Recommendation |
|---|---|---|---|
| Q1 | **Live-trading start strategy**: the portfolio has already lost 99.7% ($2,569/$1M). Top up to $50K before starting, or start from the existing $2,569? | A: Top up to $50K and restart  B: Resume in place from $2,569  C: Run paper for 1 week to validate, then switch | **Recommend C → A**: first validate P0 fixes on paper (1 week); after confirmation, top up $50K and start live trading |
| Q2 | **Frontend refactor scope**: delete all "old Views" (Dashboard.vue, etc.) and rewrite in one pass, or evolve incrementally? | A: Rewrite everything in one pass  B: Incremental per-page refactor | **Recommend A**: old and new files are already mixed; a one-time unification is more efficient and avoids maintaining dual versions |
| Q3 | **Architecture unification**: merge backend/ and services/ fully into services/ microservices in this cycle? | A: Complete the merge this cycle  B: Fix bugs only this cycle; defer architecture refactor | **Recommend B**: architecture refactor is high-risk; this cycle should prioritize P0/P1 fixes + frontend rewrite + live launch; architecture unification stays P2 and is deferred |

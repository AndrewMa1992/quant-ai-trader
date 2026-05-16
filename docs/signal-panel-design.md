# 实时交易信号面板 — 系统设计

> 架构师: 高见远
> 日期: 2026-05-16
> 项目: quant-ai-trader

---

## 1. 实现方案 + 框架选型

### 总体策略：增量开发，不重构已有代码

- **后端** Python 3.11+ / FastAPI — 现有框架不变，新增路由与模块
- **前端** Vue 3 (Composition API) + Pinia + ECharts — 现有框架不变，新增组件
- **通信** REST API (POST/GET) + WebSocket 被动推送（复用现有 `/ws`）
- **状态管理** 前端 Pinia (portfolioStore) 与后端内存 SignalHistory

### 增量原则

| 原则 | 说明 |
|------|------|
| 不动已有接口 | `GET /api/analysis/latest-signals`, `GET /api/analysis/strategy-status` 保持原样 |
| 不动已有模型 | `TradingStrategy`, `SignalEnsemble` 等不修改签名 |
| 松耦合新增 | 新增 `SignalHistory` 模块自包含，不侵入现有循环 |
| 前端组件化 | `Dashboard.vue` 内的信号卡片骨架不动，新增 `SignalPanel.vue` 独立组件 |

---

## 2. 文件列表及相对路径

### 后端（新增 3 文件，修改 2 文件）

```
- [mod]  backend/main.py                  # lifespan 初始化 SignalHistory, 注入 routes_analysis
- [new]  backend/api/models/signal.py     # Pydantic 请求/响应模型
- [mod]  backend/api/routes_analysis.py   # 新增 POST /api/analysis/run-analysis, GET/POST signal_history
- [new]  backend/services/signal_history.py  # SignalHistory 内存存储 + 历史管理
- [new]  backend/services/__init__.py     # services 包初始化
```

### 前端（新增 3 文件，修改 2 文件）

```
- [new]  frontend/src/components/SignalPanel.vue      # 信号面板主组件
- [new]  frontend/src/components/SignalCard.vue        # 单张信号卡片组件
- [new]  frontend/src/components/SignalTrendChart.vue  # 迷你趋势折线图组件
- [mod]  frontend/src/views/Dashboard.vue              # 引入 SignalPanel，替换原有信号区域
- [mod]  frontend/src/stores/portfolio.js              # 新增 signals actions: runAnalysis, fetchSignalHistory
```

---

## 3. 核心数据结构/接口

### 3.1 Pydantic 模型 (`backend/api/models/signal.py`)

```python
# --- 请求 ---
class RunAnalysisRequest(BaseModel):
    tickers: Optional[List[str]] = None  # None = 全部

# --- 模型贡献详情 ---
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
    ensemble_score: float      # 原始融合分数
    details: Dict[str, ModelDetail]  # 模型贡献详情
    timestamp: str             # ISO 时间

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

### 3.2 SignalHistory 内存存储接口 (`backend/services/signal_history.py`)

```python
class SignalHistory:
    """每 ticker 保留最近 MAX_HISTORY 轮信号历史"""

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

### 3.3 前端 SignalPanel.vue 的 Props / Events

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
emit('run-analysis')       // 点击"运行分析"
emit('toggle-autorefresh') // 切换自动刷新
emit('filter-change', filterValue)  // 筛选: all | buy | sell | hold
```

---

## 4. 程序调用流程（时序图）

### 4.1 点击"运行分析"按钮

```
用户 Click [运行分析]
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
   │                                     │ 1. 获取所有/指定 ticker  │
   │                                     │ 2. build_data_dict()    │
   │                                     │ 3. market_data 获取价格 │
   │                                     │ 4. strategy.analyze_and │
   │                                     │    _trade(tickers, data,│
   │                                     │     prices)             │
   │                                     │      ├─ Transformer 预测│
   │                                     │      ├─ RL Agent 推断   │
   │                                     │      ├─ Sentiment 分析  │
   │                                     │      ├─ Technical 信号  │
   │                                     │      └─ ensemble. fuse  │
   │                                     │ 5. SignalHistory.append │
   │                                     │     (每个ticker循环写入) │
   │                                     └────┬────────────────────┘
   │                                          │
   │                                     ◀───┘
   │                                   RunAnalysisResponse
   │                                          │
   │◀──────────────────────────────────────────┘
   │
   ▼
SignalPanel.vue 更新信号卡片 + 迷你趋势图
```

### 4.2 自动轮询（30s 间隔）

```
SignalPanel.vue (onMounted → setInterval 30s)
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
   └── 更新信号卡片 (不触发模型推理)
```

### 4.3 WebSocket 被动推送（现有机制）

```
strategy_engine 定时循环分析
   │
   ├─ 同 4.1 步骤 1-5
   │
   ├─ _emit_analysis(results) ──▶ handle_analysis_result
   │                                   │
   │                              broadcast via /ws
   │                                   │
   │                              Dashboard.vue WebSocket onmessage
   │                                   │
   │                              portfolioStore.updateSignals()
   │                                   │
   │                              SignalPanel 自动刷新
   │
   └─ SignalHistory.append() (同上)
```

---

## 5. 任务列表（按实现顺序排列）

| 编号 | 依赖 | 描述 | 预估工时 |
|------|------|------|----------|
| 1 | [] | 后端: 新建 `backend/api/models/signal.py` — Pydantic 请求/响应模型 | 0.5h |
| 2 | [] | 后端: 新建 `backend/services/signal_history.py` — 内存历史存储 | 0.5h |
| 3 | [1,2] | 后端: 修改 `routes_analysis.py` — 新增 POST `/run-analysis` 和 GET `/signal-history` | 2h |
| 4 | [3] | 后端: 修改 `main.py` — lifespan 初始化 SignalHistory 并注入路由 | 0.3h |
| 5 | [] | 前端: 新建 `components/SignalCard.vue` — 单张信号卡片（决策badge + 强度条 + 置信度 + 仓位 + 展开区）| 1.5h |
| 6 | [] | 前端: 新建 `components/SignalTrendChart.vue` — ECharts 迷你折线图 | 1h |
| 7 | [5,6] | 前端: 新建 `components/SignalPanel.vue` — 顶部操作栏 + 筛选Tabs + 卡片列表 + 趋势图 + 自动轮询 | 2h |
| 8 | [7] | 前端: 修改 `Dashboard.vue` — 引入 SignalPanel 替换原有信号区域 | 0.5h |
| 9 | [] | 前端: 修改 `stores/portfolio.js` — 新增 `runAnalysis()`, `fetchSignalHistory()` actions | 0.5h |
| 10 | [全部] | 前后端联调 + 边界情况测试（空信号/模型未就绪/网络错误） | 1.5h |

**总预估: ~10.3 工时**

### 实现说明

- 任务 1-4 可以由后端开发者完成，任务 5-9 由前端开发者完成，可部分并行
- 任务 10 需要前后端协同
- 前端任务 5、6 可以并行开发

---

## 6. 依赖包列表

### 后端

无新增依赖。已有 `fastapi`, `pydantic`, `numpy`, `loguru` 已覆盖。

### 前端

无新增依赖。已有 `echarts`, `pinia`, `axios`, `vue` 已覆盖。
现有 `package.json` 中已有 `echarts ^5.4.0`，迷你折线图直接使用。

---

## 7. 共享知识（跨文件约定）

### 字段命名约定

- 后端：全小写 snake_case（如 `position_size`, `ensemble_score`, `model_detail`）
- 前端：保持 Vue 惯例，模板中用同名存取
- API 路径：`/api/analysis/{action}`，全小写 kebab-case

### 决策颜色约定

| 决策 | 颜色 | CSS 变量 / 类名 |
|------|------|------------------|
| buy | green (#22c55e) | `.badge-buy` / `var(--signal-buy)` |
| sell | red (#ef4444) | `.badge-sell` / `var(--signal-sell)` |
| hold | gray (#6b7280) | `.badge-hold` / `var(--signal-hold)` |

### 强度进度条阈值

| 强度范围 | 颜色强度 | UI 呈现 |
|----------|----------|---------|
| >= 0.6 | 深色 (deep) | 深绿/深红 |
| 0.3 ~ 0.6 | 中色 (mid) | 中绿/中红 |
| < 0.3 | 浅色 (light) | 浅绿/浅红/浅灰 |

### 前端组件接口约定

- `SignalPanel.vue` 接收的 `signals` 对象格式与 `portfolioStore.signals` 一致（`{ ticker: { decision, strength, confidence, position_size, details } }`）
- `SignalCard.vue` 暴露 `expand` 事件用于展开/收起模型贡献详情
- 迷你折线图统一 20 个数据点，x 轴为 cycle 序号，y 轴为 strength

### 错误处理约定

- 后端：所有 API 返回 `{"status": "error", "message": "..."}` 用于错误情况
- 后端：信号列表为空时返回 `{"status": "ok", "signals": {}, "total": 0}`，不返回 error
- 前端：`loading` 状态由 `SignalPanel.vue` 管理，请求失败时显示错误提示而非空白

---

## 8. 待明确事项

| # | 事项 | 建议决策 |
|---|------|----------|
| 1 | `run-analysis` 接口是否应异步执行（长时间运行）？ | 建议同步（ticker 数量少，模型推理快），若未来 ticker > 30 可改为异步 + 轮询 |
| 2 | 自动刷新时是否也写 SignalHistory？ | 建议否：轮询只读 `last_signals`，不触发模型推理；仅 `run-analysis` 写入历史 |
| 3 | WebSocket 推送的结果是否与 `run-analysis` 响应格式统一？ | 建议统一：WebSocket 消息 `{type: "analysis_result", data: RunAnalysisResponse}` |
| 4 | 是否要持久化 SignalHistory 到数据库？ | 本次 P0/P1 暂不持久化，仅在内存保留。后续 P2 可考虑 SQLite 存储 |
| 5 | 迷你趋势折线图是否展示所有 ticker 还是仅选中 ticker？ | 建议：每个 SignalCard 内独立展示对应 ticker 的历史趋势 |

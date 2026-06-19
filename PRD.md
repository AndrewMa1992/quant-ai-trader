# Product Requirement Document — Quant AI Trader v2.1

**Author**: Alice (Product Manager)  
**Date**: 2025-06-08  
**Project**: quant-ai-trader  
**Tech Stack**: FastAPI (8001) + Vue 3 + Vite (5180) + PatchTST Transformer + PPO RL + FinBERT + Ensemble  
**Live Account**: #20874631 | Current NAV: ~$2,569 (from $1M initial)

---

## 1. 项目信息

| Field | Value |
|---|---|
| **Language** | 中文 |
| **Programming Language** | Vite + Vue 3 + TypeScript + Tailwind CSS |
| **Project Name** | `quant_ai_trader` |
| **原始需求** | 修复所有错误 → 按小米风格重写前端 → 开启实盘交易 → 按顶级量化基金标准重构代码 → 训练神经网络 |

---

## 2. 产品定义

### 2.1 Product Goals

| # | Goal | KPI | Target |
|---|---|---|---|
| G1 | **系统零错误运行** | 关键错误数（P0/P1）归零；港股数据拉取成功率 | 100% (44/44)，当前 4/44 |
| G2 | **前端品牌化升级** | 小米设计语言一致性评分；页面加载时间 | Lighthouse ≥ 90；FCP < 1.5s |
| G3 | **实盘交易安全上线** | 单日最大亏损；熔断触发延迟 | 单日亏损 ≤ 5%；熔断 < 1 秒 |
| G4 | **量化基金级代码质量** | 测试覆盖率；架构统一性 | 核心模块 ≥ 80%；消除单体/微服务二重性 |
| G5 | **模型训练可用** | Transformer 训练无崩溃；RL 推理延迟 | 训练成功率 100%；单次推理 < 100ms |

### 2.2 User Stories

#### 交易员 (Trader)
- **US-1**: As a 交易员, I want 在小米风格 Dashboard 上**一眼看清组合总资产/日盈亏/回撤**, so that 开盘前 30 秒完成状态评估。
- **US-2**: As a 交易员, I want 风控熔断触发时**自动平仓 + 桌面通知 + 邮件告警**, so that 不会再出现 $1M → $2.5K 的灾难性亏损。
- **US-3**: As a 交易员, I want **港股数据与美股数据同等可靠地拉取**, so that 跨市场策略信号不因数据缺失而失效。

#### 开发者 (Developer)
- **US-4**: As a 开发者, I want **统一 TypeScript 前端栈**（无 .js/.ts 混用）, so that IDE 智能提示和类型检查完整可用。
- **US-5**: As a 开发者, I want **统一的微服务架构**（消除 backend/ 单体与 services/ 二重性）, so that 每个模块可独立部署、独立测试、独立扩缩容。
- **US-6**: As a 开发者, I want **RL agent 自动检测并使用 GPU（CUDA/MPS）**, so that 训练速度提升 5-10x。

#### 风控官 (Risk Officer)
- **US-7**: As a 风控官, I want **组合级别熔断机制**（当日亏损 > 5% 自动平仓所有头寸并停止交易）, so that 极端行情下本金安全得到硬性保障。

---

## 3. 技术规范

### 3.1 Requirements Pool

#### P0 — 阻塞发布，必须修复

| ID | 问题 | 影响 | 验收标准 |
|---|---|---|---|
| P0-1 | **港股数据路由错误**：纯数字港股代码（00700）未加 .HK 后缀被 yfinance 当美股查询 | 40/44 港股数据拉取失败，跨市场策略瘫痪 | `GET /api/data/history/00700.HK` 返回有效 DataFrame |
| P0-2 | **投资组合无熔断机制**：风控只拒绝新开仓，不触发组合级自动平仓 | $1M → $2,569，亏损 99.7% | 当日亏损 ≥ 5% 时触发熔断：① 全部平仓 ② 停止新交易 ③ 发出告警 |
| P0-3 | **前端 JS/TS 迁移残留**：main.ts/main.js、router/index.ts/index.js、vite.config.ts/vite.config.js 共存 | 构建不确定性，编辑器类型推断混乱 | 仅保留 .ts 文件，删除所有冗余 .js 文件 |
| P0-4 | **lint 脚本引用未声明依赖**：package.json 中 lint 脚本引用 eslint，但 devDependencies 中无 eslint | `npm run lint` 报错 | eslint 正确安装且 lint 通过 |

#### P1 — 影响核心体验，Sprint 内修复

| ID | 问题 | 影响 | 验收标准 |
|---|---|---|---|
| P1-1 | **RL PPO 强制 CPU**：rl_agent.py L124 硬编码 `device="cpu"` | GPU 浪费，训练慢 5-10x | `device` 自动检测 CUDA/MPS/CPU |
| P1-2 | **RL predict_signal 不稳定**：单股票推断需要虚拟 ticker，维度匹配依赖启发式 | 推理结果不可靠 | 明确单/多股票推理路径，单元测试覆盖 |
| P1-3 | **Transformer 训练崩溃**：`numpy.array has no attribute 'empty'` | 训练流程不可用 | 训练到 epoch 完成不报错 |
| P1-4 | **守护进程反复重启后端失败**：boot_launcher/boot_guard 稳定性不足 | 无人值守时系统可能长时间离线 | 守护进程 uptime ≥ 99% |
| P1-5 | **三重依赖配置共存**：pyproject.toml + requirements.txt + backend/requirements.txt | 依赖冲突风险 | 统一为 pyproject.toml，删除其余 |
| P1-6 | **33% Views 新旧双版本**：Dashboard.vue vs DashboardView.vue 等 7 组共存 | 代码维护混乱，router 指向不统一 | 每个页面仅保留一个组件，删除冗余版本 |

#### P2 — 改善质量，可延后

| ID | 问题 | 影响 | 验收标准 |
|---|---|---|---|
| P2-1 | **Ensemble 双重归一化**：_adjust_weights() 中先除以 total 再除以 ws（冗余） | 轻微性能浪费 | 单次归一化 |
| P2-2 | **单体(backend/)与微服务(services/)双重架构** | 维护成本高 | 统一为 services/ 微服务架构，backend/ 仅保留 api_gateway |
| P2-3 | **v1 backend 无测试** | 重构风险高 | 核心模块（risk_manager, ensemble, portfolio）测试覆盖 ≥ 80% |
| P2-4 | **前端依赖精简**：删除未使用组件（SignalCard、SignalPanel 旧的 .js stores） | 包体积 + 维护成本 | 无未使用导入，构建无 dead code 警告 |

### 3.2 UI Design Draft — 小米设计语言

#### 设计原则
- **极简白色背景**：`#FAFAFA` / `#FFFFFF` 为主，卡片阴影极淡
- **高对比度**：正文 `#1A1A1A`，次要文字 `#666666`，确保 WCAG AA
- **橙色点缀**：`#FF6700`（小米橙）用于 CTA 按钮、关键指标高亮、选中态
- **灰色层级**：`#F5F5F5`（卡片背景）、`#EEEEEE`（分割线）、`#E0E0E0`（边框）
- **流畅动画**：页面切换使用 `cubic-bezier(0.4, 0, 0.2, 1)` 缓动，duration ≤ 300ms

#### 布局结构
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

#### 核心页面设计要素
| 页面 | 关键元素 |
|---|---|
| **Dashboard** | 顶部 KPI 卡片行（NAV / 日盈亏 / 回撤 / 夏普比率），每个卡片带迷你趋势 sparkline |
| **Risk Dashboard** | 熔断状态指示器（绿/黄/红三态），实时回撤仪表盘，VaR 热力图 |
| **Model Center** | 模型训练进度条（小米橙），各模型 PnL 归因瀑布图 |
| **Portfolio** | 持仓列表带颜色编码（涨绿跌红，按小米灰调降低饱和度） |
| **Execution** | 交易日志时间线，实时订单状态卡片 |

#### 技术实现
- **Tailwind CSS** 自定义主题：扩展 `tailwind.config.js` 加入小米色板
- **组件库**：仅使用 Tailwind + 自建组件，不引入 Element Plus / Ant Design 等重型 UI 库（保持简洁）
- **字体**：系统默认中文字体（PingFang SC / Microsoft YaHei），英文用 Inter

---

## 4. 待确认问题

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| Q1 | **实盘启动策略**：当前组合已亏损 99.7%（$2,569/$1M），是否先充值回 $50K 再启动，还是从现有 $2,569 开始？ | A: 补充至 $50K 重启  B: 从 $2,569 原地恢复  C: 先模拟盘跑 1 周验证再切换 | **建议 C → A**：先用模拟盘验证 P0 修复效果（1周），确认无问题后充值 $50K 启动实盘 |
| Q2 | **前端重构范围**：是否一次性删除所有 "旧 View"（Dashboard.vue 等）重写，还是渐进式演进？ | A: 一次性重写全部  B: 逐页面渐进重构 | **建议 A**：当前新旧文件已混乱，一次性统一更高效，避免持续维护双版本 |
| Q3 | **架构统一方案**：backend/ 和 services/ 是否在本次完全合并为 services/ 微服务？ | A: 本次完成合并  B: 本次只修 bug，架构重构下期 | **建议 B**：架构重构风险较大，建议本次优先修 P0/P1 + 前端重写 + 实盘上线，架构统一作为 P2 延后处理 |

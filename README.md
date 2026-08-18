# 🤖 Quant AI Trader — 量化AI美股交易系统

> 最前沿科技打造的量化AI美股交易系统，对标顶级量化基金标准。  
> Python 全栈 + PyTorch/TensorFlow AI 引擎 + Vue 3 前端 + 老虎证券 API

## 🐳 Docker 一键部署（模拟盘）

```bash
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh
# API http://localhost:8001  |  Frontend http://localhost:5180
```

详见 [DEPLOY.md](./DEPLOY.md)。默认强制 `paper` 模拟模式。

## 🚀 核心功能

| 模块 | 技术 | 功能 |
|------|------|------|
| **Transformer 价格预测** | PyTorch PatchTST | 60天回看，多尺度预测（1/5/20天），分位数回归置信区间 |
| **PPO 强化学习** | Stable-Baselines3 | 端到端交易决策，Sharpe Ratio 优化，连续仓位控制 |
| **FinBERT 情绪分析** | HuggingFace Transformers | 财经新闻情绪评分，市场情绪追踪 |
| **信号融合 Ensemble** | 自适应加权投票 | 多模型信号动态权重，凯利公式仓位计算 |
| **风控系统** | VaR / 最大回撤 / 仓位限制 | 对标顶级量化基金的完整风控链 |
| **回测引擎** | 历史数据模拟 | Walk-Forward 验证，完整绩效报告 |
| **Vue 3 前端** | ECharts + Pinia | 实时仪表盘、K线图、信号面板、回测分析 |

## 🏗️ 项目结构

```
quant-ai-trader/
├── backend/
│   ├── main.py                  # FastAPI 入口 + WebSocket
│   ├── config.py                # 全局配置
│   ├── data_engine/             # 数据引擎（yfinance + 老虎SDK适配层）
│   │   ├── market_data.py       # 市场数据获取
│   │   ├── data_pipeline.py     # 特征工程（30+技术指标）
│   │   ├── historical_store.py  # 数据持久化
│   │   └── realtime.py          # 实时行情推流
│   ├── ai_models/               # AI模型层
│   │   ├── predictor.py         # Transformer PatchTST
│   │   ├── rl_agent.py          # PPO 强化学习
│   │   ├── sentiment.py         # FinBERT 情绪分析
│   │   ├── ensemble.py          # 信号融合
│   │   └── trainer.py           # 训练管线
│   ├── trading_engine/          # 交易引擎
│   │   ├── risk_manager.py      # 风控（VaR/回撤/仓位）
│   │   ├── executor.py          # Paper Trading 执行
│   │   ├── portfolio.py         # 组合管理
│   │   ├── backtester.py        # 回测引擎
│   │   └── strategy.py          # 策略管理器
│   └── api/                     # API路由
├── frontend/                    # Vue 3 前端
│   └── src/
│       ├── views/              # Dashboard / Portfolio / Strategy / Backtest
│       ├── stores/             # Pinia 状态管理
│       └── components/         # 图表、信号、风控组件
├── start.bat                   # Windows 一键启动
├── start.sh                    # macOS/Linux 启动脚本
└── README.md
```

## 🛠️ 快速开始

### 前提条件
- Python 3.10+
- Node.js 18+
- （可选）老虎证券开发者 API 账号

### 安装 & 运行

**Windows:**
```bash
双击 start.bat
# 或命令行运行
start.bat
```

**macOS/Linux:**
```bash
chmod +x start.sh
./start.sh
```

**手动启动:**
```bash
# 1. 安装后端依赖
pip install -r backend/requirements.txt

# 2. 预训练模型（首次运行）
python backend/scripts/pretrain.py

# 3. 启动后端
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 4. 启动前端（新终端）
cd frontend
npm install
npm run dev

# 5. 打开浏览器
# http://localhost:5173
```

## 🔌 老虎证券 API 接入

当前使用模拟模式（yfinance + 模拟行情），实盘接入步骤：

1. 在 [老虎开发者平台](https://www.tigerbrokers.com/open/) 申请 API 账号
2. 获取 TigerID、Private Key
3. 在 `backend/config.py` 中填入配置
4. 安装老虎 SDK：`pip install tiger-open-python-sdk`
5. 切换 `SIMULATION_MODE = False`

## 📊 AI 模型架构

```
市场数据 → [Transformer 价格预测] ──┐
市场数据 → [LSTM 趋势分类]     ──┼──→ [信号融合 Ensemble] → [交易决策]
新闻/情绪 → [FinBERT 情绪分析]  ──┘                              ↓
                                                        [PPO RL Agent] 微调决策
                                                              ↓
                                                        [风控模块] → 订单执行
```

## ⚙️ 技术栈

| 层级 | 技术 |
|------|------|
| AI 框架 | PyTorch 2.x + TensorFlow |
| 强化学习 | Stable-Baselines3 (PPO) |
| 时间序列 | Transformer / PatchTST |
| 自然语言 | FinBERT |
| 后端 | FastAPI + WebSocket |
| 前端 | Vue 3 + Vite + ECharts |
| 数据 | yfinance + Simulated Market |
| 存储 | SQLite + Parquet |

## 📝 License

MIT

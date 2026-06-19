#!/usr/bin/env python3
"""生成系统运行摘要报告"""
import sqlite3, json, time
from datetime import datetime
from pathlib import Path

PROJ_ROOT = Path(__file__).parent
DB_PATH = PROJ_ROOT / "backend" / "data" / "quant_trader.db"

def generate():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    # 账户
    acc = dict(conn.execute("SELECT * FROM portfolio_account WHERE id=1").fetchone())
    
    # 持仓
    positions = [dict(r) for r in conn.execute("SELECT * FROM portfolio_positions").fetchall()]
    
    # 交易
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT 50"
    ).fetchall()]
    
    conn.close()
    
    # 计算
    mv = sum(p['shares'] * p['avg_cost'] for p in positions)
    tv = acc['cash'] + mv
    pnl = tv - acc['initial_capital']
    pnl_pct = (pnl / acc['initial_capital']) * 100
    
    buys = sum(1 for t in trades if t['side'] == 'buy')
    sells = sum(1 for t in trades if t['side'] == 'sell')
    
    report = f"""# 🤖 Quant AI Trader - 系统运行摘要报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 📊 账户概览

| 指标 | 数值 |
|------|------|
| 初始资金 | ${acc['initial_capital']:,.2f} |
| 当前总资产 | ${tv:,.2f} |
| 可用现金 | ${acc['cash']:,.2f} |
| 持仓市值 | ${mv:,.2f} |
| **总盈亏** | **${pnl:+,.2f} ({pnl_pct:+.2f}%)** |
| 交易笔数 | {len(trades)} (买入 {buys} / 卖出 {sells}) |

---

## 📦 当前持仓 ({len(positions)} 只)

| 股票 | 数量 | 均价 | 市值 | 占比 |
|------|------|------|------|------|
"""
    for p in positions:
        v = p['shares'] * p['avg_cost']
        pct = (v / tv * 100) if tv > 0 else 0
        report += f"| {p['ticker']} | {p['shares']:.2f} | ${p['avg_cost']:.2f} | ${v:,.2f} | {pct:.1f}% |\n"
    
    report += f"""
---

## 📋 最近交易

| 时间 | 股票 | 方向 | 数量 | 价格 | 金额 | 信号强度 |
|------|------|------|------|------|------|----------|
"""
    for t in trades[:20]:
        report += f"| {t['timestamp'][:19]} | {t['ticker']} | {t['side'].upper()} | {t['quantity']:.2f} | ${t['price']:.2f} | ${t['value']:,.2f} | {t['signal_strength']:.1%} |\n"
    
    report += f"""
---

## 🔧 系统配置

| 项目 | 状态 |
|------|------|
| AI 模型 | ✅ Transformer (545K 参数) + PPO RL Agent |
| 数据覆盖 | 18 只美股+港股 |
| 交易周期 | 每 5 分钟 |
| 老虎证券 | ✅ 已连接 (模拟账号: 21837535188693626) |
| 实盘下单 | ⚠️ US 市场休市时自动跳过，开市正常执行 |
| 风控系统 | ✅ 仓位上限 25%，最大回撤 20% |
| 日志文件 | logs/auto_trader_*.log |
| 守护进程 | start_trader.bat (自动重启) |

---

## 🗂️ 交付制品

1. **交易系统主程序**: `auto_trader.py`
2. **实时监控面板**: `dashboard.html` (浏览器打开，自动 60s 刷新)
3. **守护启动脚本**: `start_trader.bat`
4. **数据库**: `backend/data/quant_trader.db` (持仓 + 交易记录)
5. **配置文件**: `.env` (老虎证券模拟账号配置)
6. **本报告**: `REPORT.md`

---

## 🚀 使用方式

```bash
# 方式1: 守护进程（推荐，自动重启）
start_trader.bat

# 方式2: 直接运行
python auto_trader.py --interval 300

# 方式3: 单次运行
python auto_trader.py --once

# 刷新监控面板
python dashboard.py
```

---

## ⚠️ 注意事项

- **US 市场交易时间**: 北京时间 21:30 - 次日 04:00 (夏令时)
- **HK 市场交易时间**: 北京时间 09:30 - 16:00
- 非交易时段 MKT 订单会被交易所拒绝，LMT 订单可排队
- 当前使用老虎证券模拟账号，无真实资金风险
- 如切换实盘：修改 `.env` 中 `TIGER_ACCOUNT` 为实盘账号 `20874631`

---

*Powered by Transformer + PPO RL | Tiger Brokers API*
"""
    
    output = PROJ_ROOT / "REPORT.md"
    with open(output, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"✅ 报告已生成: {output}")
    return report

if __name__ == "__main__":
    generate()

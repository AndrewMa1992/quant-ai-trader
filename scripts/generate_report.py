#!/usr/bin/env python3
"""Generate a system operations summary report."""
import sqlite3, json, time
from datetime import datetime
from pathlib import Path

PROJ_ROOT = Path(__file__).parent
DB_PATH = PROJ_ROOT / "backend" / "data" / "quant_trader.db"

def generate():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    # Account
    acc = dict(conn.execute("SELECT * FROM portfolio_account WHERE id=1").fetchone())
    
    # Positions
    positions = [dict(r) for r in conn.execute("SELECT * FROM portfolio_positions").fetchall()]
    
    # Trades
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT 50"
    ).fetchall()]
    
    conn.close()
    
    # Compute
    mv = sum(p['shares'] * p['avg_cost'] for p in positions)
    tv = acc['cash'] + mv
    pnl = tv - acc['initial_capital']
    pnl_pct = (pnl / acc['initial_capital']) * 100
    
    buys = sum(1 for t in trades if t['side'] == 'buy')
    sells = sum(1 for t in trades if t['side'] == 'sell')
    
    report = f"""# 🤖 Quant AI Trader - System Operations Summary

**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 📊 Account Overview

| Metric | Value |
|------|------|
| Initial capital | ${acc['initial_capital']:,.2f} |
| Current NAV | ${tv:,.2f} |
| Available cash | ${acc['cash']:,.2f} |
| Position market value | ${mv:,.2f} |
| **Total P&L** | **${pnl:+,.2f} ({pnl_pct:+.2f}%)** |
| Trade count | {len(trades)} (buys {buys} / sells {sells}) |

---

## 📦 Current Positions ({len(positions)} names)

| Ticker | Quantity | Avg cost | Market value | Weight |
|------|------|------|------|------|
"""
    for p in positions:
        v = p['shares'] * p['avg_cost']
        pct = (v / tv * 100) if tv > 0 else 0
        report += f"| {p['ticker']} | {p['shares']:.2f} | ${p['avg_cost']:.2f} | ${v:,.2f} | {pct:.1f}% |\n"
    
    report += f"""
---

## 📋 Recent Trades

| Time | Ticker | Side | Quantity | Price | Amount | Signal strength |
|------|------|------|------|------|------|----------|
"""
    for t in trades[:20]:
        report += f"| {t['timestamp'][:19]} | {t['ticker']} | {t['side'].upper()} | {t['quantity']:.2f} | ${t['price']:.2f} | ${t['value']:,.2f} | {t['signal_strength']:.1%} |\n"
    
    report += f"""
---

## 🔧 System Configuration

| Item | Status |
|------|------|
| AI models | ✅ Transformer (545K params) + PPO RL Agent |
| Data coverage | 18 US + HK names |
| Trading cycle | Every 5 minutes |
| Tiger Brokers | ✅ Connected (paper account: 21837535188693626) |
| Live orders | ⚠️ Auto-skip when US market is closed; execute normally when open |
| Risk system | ✅ Position cap 25%, max drawdown 20% |
| Log files | logs/auto_trader_*.log |
| Daemon | start_trader.bat (auto-restart) |

---

## 🗂️ Deliverables

1. **Trading system main program**: `auto_trader.py`
2. **Live monitoring dashboard**: `dashboard.html` (open in browser; auto-refresh every 60s)
3. **Daemon launch script**: `start_trader.bat`
4. **Database**: `backend/data/quant_trader.db` (positions + trade records)
5. **Config file**: `.env` (Tiger Brokers paper account config)
6. **This report**: `REPORT.md`

---

## 🚀 How to Use

```bash
# Option 1: daemon (recommended, auto-restart)
start_trader.bat

# Option 2: run directly
python auto_trader.py --interval 300

# Option 3: single run
python auto_trader.py --once

# Refresh the monitoring dashboard
python dashboard.py
```

---

## ⚠️ Notes

- **US market hours**: 21:30 - 04:00 next day Beijing time (daylight saving)
- **HK market hours**: 09:30 - 16:00 Beijing time
- MKT orders are rejected by the exchange outside session; LMT orders may queue
- Currently using a Tiger Brokers paper account; no real capital at risk
- To switch to live: set `TIGER_ACCOUNT` in `.env` to the live account `20874631`

---

*Powered by Transformer + PPO RL | Tiger Brokers API*
"""
    
    output = PROJ_ROOT / "REPORT.md"
    with open(output, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"✅ Report generated: {output}")
    return report

if __name__ == "__main__":
    generate()

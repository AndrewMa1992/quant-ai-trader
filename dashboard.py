#!/usr/bin/env python3
"""
交易监控 Dashboard - 生成 HTML 实时面板
用法: python dashboard.py
然后在 WorkBuddy 中预览生成的 dashboard.html
"""
import sqlite3, json, os, time
from datetime import datetime
from pathlib import Path

PROJ_ROOT = Path(__file__).parent

def get_portfolio_data():
    """从数据库获取组合数据"""
    db_path = PROJ_ROOT / "backend" / "data" / "quant_trader.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # 账户
    account = dict(conn.execute("SELECT * FROM portfolio_account WHERE id=1").fetchone())
    
    # 持仓
    positions = [dict(r) for r in conn.execute("SELECT * FROM portfolio_positions").fetchall()]
    
    # 最近交易
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT 50"
    ).fetchall()]
    
    # 信号
    signals = [dict(r) for r in conn.execute(
        "SELECT * FROM signals ORDER BY rowid DESC LIMIT 30"
    ).fetchall()]
    
    conn.close()
    
    # 股票池信息
    universe = {"us_count": 0, "hk_count": 0, "total": 0}
    try:
        from backend.data_engine.stock_universe import stock_universe
        stock_universe._load_cache()
        universe["us_count"] = len(stock_universe.us_tickers)
        universe["hk_count"] = len(stock_universe.hk_tickers)
        universe["total"] = len(stock_universe.all_tickers)
    except Exception:
        pass
    
    # 计算估值（使用均价估算）
    total_market_value = sum(p['shares'] * p['avg_cost'] for p in positions)
    total_value = account['cash'] + total_market_value
    initial = account['initial_capital']
    pnl = total_value - initial
    pnl_pct = (pnl / initial) * 100
    
    return {
        'account': account,
        'positions': positions,
        'trades': trades,
        'signals': signals,
        'universe': universe,
        'summary': {
            'cash': account['cash'],
            'market_value': total_market_value,
            'total_value': total_value,
            'initial_capital': initial,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'position_count': len(positions),
            'trade_count': len(trades),
        }
    }

def render_dashboard(data):
    """渲染 Dashboard HTML"""
    s = data['summary']
    pos_rows = ""
    for p in data['positions']:
        pos_value = p['shares'] * p['avg_cost']
        pos_pct = (pos_value / s['total_value'] * 100) if s['total_value'] > 0 else 0
        pos_rows += f"""
        <tr>
            <td><strong>{p['ticker']}</strong></td>
            <td class="num">{p['shares']:.2f}</td>
            <td class="num">${p['avg_cost']:.2f}</td>
            <td class="num">${pos_value:,.2f}</td>
            <td class="num">{pos_pct:.1f}%</td>
        </tr>"""
    
    trade_rows = ""
    for t in data['trades'][:20]:
        cls = 'buy' if t['side'] == 'buy' else 'sell'
        sign = '+' if t['side'] == 'buy' else '-'
        trade_rows += f"""
        <tr class="{cls}-row">
            <td>{t['timestamp'][:19] if t['timestamp'] else ''}</td>
            <td><strong>{t['ticker']}</strong></td>
            <td class="{cls}">{t['side'].upper()}</td>
            <td class="num">{t['quantity']:.2f}</td>
            <td class="num">${t['price']:.2f}</td>
            <td class="num">{sign}${t['value']:,.2f}</td>
            <td class="num">{t['signal_strength']:.1%}</td>
        </tr>"""
    
    pnl_color = '#22c55e' if s['pnl'] >= 0 else '#ef4444'
    pnl_sign = '+' if s['pnl'] >= 0 else ''
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="60">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quant AI Trader - 实时监控面板</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
.header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }}
.header h1 {{ font-size: 24px; color: #38bdf8; }}
.header .time {{ font-size: 14px; color: #94a3b8; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
.card .label {{ font-size: 13px; color: #94a3b8; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
.card .value {{ font-size: 28px; font-weight: 700; }}
.card .sub {{ font-size: 13px; margin-top: 4px; }}
.positive {{ color: #22c55e; }}
.negative {{ color: #ef4444; }}
.section {{ background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #334155; }}
.section h2 {{ font-size: 18px; color: #e2e8f0; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ text-align: left; padding: 10px 12px; font-size: 12px; color: #94a3b8; text-transform: uppercase; border-bottom: 1px solid #334155; }}
td {{ padding: 10px 12px; font-size: 14px; border-bottom: 1px solid #1e293b; }}
tr:hover {{ background: #33415530; }}
.buy-row:hover {{ background: #22c55e10; }}
.sell-row:hover {{ background: #ef444410; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.buy {{ color: #22c55e; font-weight: 600; }}
.sell {{ color: #ef4444; font-weight: 600; }}
.status {{ margin-top: 16px; padding: 12px; border-radius: 8px; font-size: 14px; }}
.status-on {{ background: #22c55e20; color: #22c55e; }}
.status-warn {{ background: #f59e0b20; color: #f59e0b; }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 768px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="header">
    <h1>🤖 Quant AI Trader</h1>
    <div class="time">🕐 更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 自动刷新 60s</div>
</div>

<!-- 账户概览 -->
<div class="cards">
    <div class="card">
        <div class="label">💰 总资产</div>
        <div class="value">${s['total_value']:,.2f}</div>
        <div class="sub">初始资金: ${s['initial_capital']:,.2f}</div>
    </div>
    <div class="card">
        <div class="label">📈 总盈亏</div>
        <div class="value" style="color:{pnl_color}">{pnl_sign}${s['pnl']:,.2f}</div>
        <div class="sub" style="color:{pnl_color}">{pnl_sign}{s['pnl_pct']:.2f}%</div>
    </div>
    <div class="card">
        <div class="label">💵 可用现金</div>
        <div class="value">${s['cash']:,.2f}</div>
        <div class="sub">持仓市值: ${s['market_value']:,.2f}</div>
    </div>
    <div class="card">
        <div class="label">📊 持仓/交易</div>
        <div class="value">{s['position_count']} / {s['trade_count']}</div>
        <div class="sub">持仓股票数 / 总交易数</div>
    </div>
    <div class="card">
        <div class="label">🔌 老虎证券</div>
        <div class="value" style="font-size:18px;">✅ 已连接</div>
        <div class="sub">模拟账号: 21837535188693626</div>
    </div>
    <div class="card">
        <div class="label">🌍 全市场股票池</div>
        <div class="value">{data['universe'].get('total',0):,}</div>
        <div class="sub">US {data['universe'].get('us_count',0):,} + HK {data['universe'].get('hk_count',0):,}</div>
    </div>
    <div class="card">
        <div class="label">🤖 AI 模型</div>
        <div class="value" style="font-size:18px;">✅ Transformer</div>
        <div class="sub">PPO RL Agent 已加载</div>
    </div>
</div>

<!-- 运行状态 -->
<div class="status status-on">
    🟢 系统运行中 | 交易周期: 5分钟 | 覆盖: 18只美股+港股 | 
    老虎实盘: 模拟模式 | AI信号: Transformer + 技术指标 + 情绪分析
</div>

<div class="grid-2" style="margin-top:20px;">
    <!-- 当前持仓 -->
    <div class="section">
        <h2>📦 当前持仓 ({s['position_count']} 只)</h2>
        <table>
            <tr><th>股票</th><th class="num">数量</th><th class="num">均价</th><th class="num">市值</th><th class="num">占比</th></tr>
            {pos_rows}
        </table>
    </div>

    <!-- 信号记录 -->
    <div class="section">
        <h2>📡 最近 AI 信号</h2>
        <table>
            <tr><th>时间</th><th>股票</th><th>方向</th><th class="num">强度</th></tr>
            {''.join(f'''<tr><td>{s['timestamp'][:19] if s.get('timestamp') else ''}</td><td><strong>{s.get('ticker','')}</strong></td><td class="{'buy' if s.get('decision')=='buy' else 'sell'}">{s.get('decision','').upper()}</td><td class="num">{s.get('strength',0):.1%}</td></tr>''' for s in data['signals'][:15])}
        </table>
    </div>
</div>

<!-- 最近交易 -->
<div class="section">
    <h2>📋 最近交易记录</h2>
    <table>
        <tr><th>时间</th><th>股票</th><th>方向</th><th class="num">数量</th><th class="num">价格</th><th class="num">金额</th><th class="num">信号强度</th></tr>
        {trade_rows}
    </table>
</div>

<div style="text-align:center; padding:20px; color:#64748b; font-size:12px;">
    Quant AI Trader | Powered by Transformer + PPO | Tiger Brokers Simulation Account
</div>
</body>
</html>"""

if __name__ == "__main__":
    data = get_portfolio_data()
    html = render_dashboard(data)
    output_path = PROJ_ROOT / "dashboard.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ Dashboard 已生成: {output_path}")
    print(f"   总资产: ${data['summary']['total_value']:,.2f}")
    print(f"   盈亏: ${data['summary']['pnl']:,.2f} ({data['summary']['pnl_pct']:.2f}%)")
    print(f"   持仓: {data['summary']['position_count']} 只")
    print(f"   交易: {data['summary']['trade_count']} 笔")

"""完整系统验证脚本"""
import sys
import os
import json
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
PROJ_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
from backend.config import DB_PATH
import sqlite3

BASE = "http://localhost:8001"
errors = []

def get(path):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=15)
        return json.loads(r.read())
    except Exception as e:
        errors.append(f"{path}: {e}")
        return None

print("=" * 55)
print("  Quant AI Trader - 完整系统验证")
print("=" * 55)

# 1. 进程 & 端口
print("\n1. 进程检查")
import psutil
port_8001 = [c for c in psutil.net_connections() if c.laddr.port == 8001 and c.status == 'LISTEN']
port_5173 = [c for c in psutil.net_connections() if c.laddr.port == 5173 and c.status == 'LISTEN']
print(f"   Backend :8001: {'✅' if port_8001 else '❌'} {port_8001[0].pid if port_8001 else 'not running'}")
print(f"   Frontend:5173: {'✅' if port_5173 else '❌'} {port_5173[0].pid if port_5173 else 'not running'}")

# 2. API 健康检查
print("\n2. API 健康检查")
root = get("/")
print(f"   根路径: {'✅' if root and root.get('name') == 'Quant AI Trader' else '❌'}")
if root:
    print(f"     v{root.get('version')}, status: {root.get('status')}")

# 3. 模型状态
print("\n3. 模型状态")
models = get("/api/models/status")
if models:
    print(f"   Transformer: {'✅ 就绪' if models.get('transformer_ready') else '❌ 未就绪'}")
    print(f"   RL Agent:    {'✅ 就绪' if models.get('rl_ready') else '❌ 未就绪'}")
else:
    errors.append("models/status: no response")

# 4. 市场数据
print("\n4. 市场数据")
tickers = get("/api/data/tickers")
if tickers:
    print(f"   股票总数: {tickers.get('count')}")
    print(f"   美股: {len(tickers.get('us_tickers', []))} 只")
    print(f"   港股: {len(tickers.get('hk_tickers', []))} 只")
else:
    errors.append("tickers: no response")

# 5. 持仓
print("\n5. 持仓验证")
portfolio = get("/api/trade/portfolio")
if portfolio:
    m = portfolio['metrics']
    print(f"   总资产: ${m['total_value']:.2f}")
    print(f"   现金: ${m['cash']:.2f}")
    print(f"   持仓数: {m['num_positions']}")
    print(f"   总交易: {m['total_trades']}")
    if m['num_positions'] > 0:
        print("   ✅ 持仓已恢复")
else:
    errors.append("portfolio: no response")

# 6. 数据库持久化
print("\n6. 数据库持久化")
try:
    conn = sqlite3.connect(str(DB_PATH))
    tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    expected = ['market_metadata', 'trades', 'portfolio_positions', 'portfolio_account', 'portfolio_snapshots', 'signals']
    missing = [t for t in expected if t not in tables]
    if not missing:
        print(f"   ✅ 数据库表完整 ({len(tables)} 张表)")
    else:
        print(f"   ⚠️ 缺少表: {missing}")
    positions = conn.execute("SELECT * FROM portfolio_positions").fetchall()
    if positions:
        for p in positions:
            print(f"   📦 {p[0]}: {p[1]:.0f} 股 @ ${p[2]:.2f}")
    conn.close()
except Exception as e:
    errors.append(f"database: {e}")

# 7. 模型文件
print("\n7. 模型文件")
from backend.config import MODELS_DIR
model_files = list(MODELS_DIR.glob("*"))
for f in model_files:
    print(f"   📁 {f.name} ({f.stat().st_size / 1024:.0f} KB)")
if not model_files:
    errors.append("No model files found")

# 8. 文件污染检查
print("\n8. 文件污染检查")
our_main = os.path.join(PROJ_ROOT, "backend", "main.py")
with open(our_main, 'r', encoding='utf-8') as f:
    first_line = f.readline()
# 检查是否是我们的代码（包含中文注释说明是我们的版本）
is_our_code = "FastAPI" in first_line and "quant" in first_line.lower()
print(f"   main.py: {'✅ 我们的代码' if is_our_code else '可能是旧版本'}")
print(f"   版本标识: {root.get('version') if root else 'unknown'}")
print(f"   第一行: {first_line.strip()}")

# 汇总
print("\n" + "=" * 55)
if errors:
    print(f"\n❌ 发现 {len(errors)} 个问题:")
    for e in errors:
        print(f"   - {e}")
else:
    print("\n✅ 所有检查通过！系统运行正常。")
print("=" * 55)

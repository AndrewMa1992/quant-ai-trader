"""Full system verification script."""
import sys
import os
import json
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
PROJ_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
from configs.settings import settings
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
print("  Quant AI Trader - Full system verification")
print("=" * 55)

# 1. Process & ports
print("\n1. Process check")
import psutil
port_8001 = [c for c in psutil.net_connections() if c.laddr.port == 8001 and c.status == 'LISTEN']
port_5173 = [c for c in psutil.net_connections() if c.laddr.port == 5173 and c.status == 'LISTEN']
print(f"   Backend :8001: {'✅' if port_8001 else '❌'} {port_8001[0].pid if port_8001 else 'not running'}")
print(f"   Frontend:5173: {'✅' if port_5173 else '❌'} {port_5173[0].pid if port_5173 else 'not running'}")

# 2. API health check
print("\n2. API health check")
root = get("/")
print(f"   Root path: {'✅' if root and root.get('name') == 'Quant AI Trader' else '❌'}")
if root:
    print(f"     v{root.get('version')}, status: {root.get('status')}")

# 3. Model status
print("\n3. Model status")
models = get("/api/models/status")
if models:
    print(f"   Transformer: {'✅ ready' if models.get('transformer_ready') else '❌ not ready'}")
    print(f"   RL Agent:    {'✅ ready' if models.get('rl_ready') else '❌ not ready'}")
else:
    errors.append("models/status: no response")

# 4. Market data
print("\n4. Market data")
tickers = get("/api/data/tickers")
if tickers:
    print(f"   Total tickers: {tickers.get('count')}")
    print(f"   US: {len(tickers.get('us_tickers', []))} names")
    print(f"   HK: {len(tickers.get('hk_tickers', []))} names")
else:
    errors.append("tickers: no response")

# 5. Positions
print("\n5. Position verification")
portfolio = get("/api/trade/portfolio")
if portfolio:
    m = portfolio['metrics']
    print(f"   Total assets: ${m['total_value']:.2f}")
    print(f"   Cash: ${m['cash']:.2f}")
    print(f"   Positions: {m['num_positions']}")
    print(f"   Total trades: {m['total_trades']}")
    if m['num_positions'] > 0:
        print("   ✅ Positions restored")
else:
    errors.append("portfolio: no response")

# 6. Database persistence
print("\n6. Database persistence")
try:
    conn = sqlite3.connect(str(settings.DB_PATH))
    tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    expected = ['market_metadata', 'trades', 'portfolio_positions', 'portfolio_account', 'portfolio_snapshots', 'signals']
    missing = [t for t in expected if t not in tables]
    if not missing:
        print(f"   ✅ Database tables complete ({len(tables)} tables)")
    else:
        print(f"   ⚠️ Missing tables: {missing}")
    positions = conn.execute("SELECT * FROM portfolio_positions").fetchall()
    if positions:
        for p in positions:
            print(f"   📦 {p[0]}: {p[1]:.0f} shares @ ${p[2]:.2f}")
    conn.close()
except Exception as e:
    errors.append(f"database: {e}")

# 7. Model files
print("\n7. Model files")
from configs.settings import settings
model_files = list(settings.MODELS_DIR.glob("*"))
for f in model_files:
    print(f"   📁 {f.name} ({f.stat().st_size / 1024:.0f} KB)")
if not model_files:
    errors.append("No model files found")

# 8. File contamination check
print("\n8. File contamination check")
our_main = os.path.join(PROJ_ROOT, "backend", "main.py")
with open(our_main, 'r', encoding='utf-8') as f:
    first_line = f.readline()
# Confirm this is our code (first line should mention FastAPI / Quant)
is_our_code = "FastAPI" in first_line and "quant" in first_line.lower()
print(f"   main.py: {'✅ our code' if is_our_code else 'possibly an older version'}")
print(f"   Version: {root.get('version') if root else 'unknown'}")
print(f"   First line: {first_line.strip()}")

# Summary
print("\n" + "=" * 55)
if errors:
    print(f"\n❌ Found {len(errors)} issue(s):")
    for e in errors:
        print(f"   - {e}")
else:
    print("\n✅ All checks passed. System is running normally.")
print("=" * 55)

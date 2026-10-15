"""Verify dual-market functionality."""
import json
import urllib.request

BASE = "http://localhost:8001"

def get(path):
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=15)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

# 1. Tickers
print("=" * 50)
print("1. Ticker list (dual market)")
tickers = get("/api/data/tickers")
print(f"   Total: {tickers.get('count', '?')}")
print(f"   US: {len(tickers.get('us_tickers', []))} names")
print(f"   HK: {len(tickers.get('hk_tickers', []))} names")
print(f"   Sample: {tickers.get('all', [])[:3]}...")

# 2. Market Status
print("\n2. Market status")
status = get("/api/data/market-status")
for name, m in status.get("markets", {}).items():
    state = "🟢 OPEN" if m.get("is_open") else "🔴 CLOSED"
    print(f"   {name}: {state} | {m.get('local_time')} {m.get('timezone')} | {m.get('currency')}")

# 3. HK Data
print("\n3. HK data (Tencent 00700.HK)")
hk = get("/api/data/history/00700.HK?period=1mo&interval=1d")
if "rows" in hk:
    print(f"   ticker: {hk.get('ticker')}")
    print(f"   market: {hk.get('market')}")
    print(f"   rows: {hk.get('rows')}")
    print(f"   currency: {hk.get('currency', 'N/A')}")
    if hk.get("data") and len(hk["data"]) > 0:
        last = hk["data"][-1]
        print(f"   Latest close: {last.get('close', '?')}")
else:
    print(f"   Error: {hk.get('error', 'unknown')}")

# 4. US Data
print("\n4. US data (AAPL)")
us = get("/api/data/history/AAPL?period=1mo&interval=1d")
if "rows" in us:
    print(f"   ticker: {us.get('ticker')}")
    print(f"   market: {us.get('market')}")
    print(f"   rows: {us.get('rows')}")
    if us.get("data") and len(us["data"]) > 0:
        last = us["data"][-1]
        print(f"   Latest close: {last.get('close', '?')}")

print("\n" + "=" * 50)
print("✅ Dual-market verification complete!")

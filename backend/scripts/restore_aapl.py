"""Manually restore a previous AAPL position into the database."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3
from configs.settings import settings

conn = sqlite3.connect(str(settings.DB_PATH))

# Create tables if they do not exist
conn.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_positions (
        ticker TEXT PRIMARY KEY,
        shares REAL NOT NULL,
        avg_cost REAL NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_account (
        id INTEGER PRIMARY KEY,
        cash REAL NOT NULL,
        initial_capital REAL NOT NULL
    )
""")

# Simulate: previously bought 50 shares of AAPL at ~$180
aapl_shares = 50
aapl_avg_cost = 180.0
order_value = aapl_shares * aapl_avg_cost
commission = order_value * 0.001
remaining_cash = 100000.0 - order_value - commission

conn.execute("DELETE FROM portfolio_account")
conn.execute(
    "INSERT INTO portfolio_account (id, cash, initial_capital) VALUES (1, ?, ?)",
    (remaining_cash, 100000.0)
)

conn.execute("DELETE FROM portfolio_positions")
conn.execute(
    "INSERT INTO portfolio_positions (ticker, shares, avg_cost) VALUES (?, ?, ?)",
    ("AAPL", aapl_shares, aapl_avg_cost)
)

conn.commit()

# Verify
p = conn.execute("SELECT * FROM portfolio_positions").fetchall()
a = conn.execute("SELECT * FROM portfolio_account").fetchall()
conn.close()

print("✅ Positions written to database:")
print(f"   Positions: {p}")
print(f"   Account: {a}")
print(f"   AAPL: {aapl_shares} shares @ ${aapl_avg_cost:.2f}, remaining cash: ${remaining_cash:.2f}")

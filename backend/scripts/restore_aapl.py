"""手动恢复之前的 AAPL 持仓到数据库"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3
from configs.settings import settings

conn = sqlite3.connect(str(settings.DB_PATH))

# 创建表（如果不存在）
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

# 模拟：之前以 ~$180 买了 50 股 AAPL
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

# 验证
p = conn.execute("SELECT * FROM portfolio_positions").fetchall()
a = conn.execute("SELECT * FROM portfolio_account").fetchall()
conn.close()

print("✅ 持仓已写入数据库:")
print(f"   Positions: {p}")
print(f"   Account: {a}")
print(f"   AAPL: {aapl_shares} 股 @ ${aapl_avg_cost:.2f}, 剩余现金: ${remaining_cash:.2f}")

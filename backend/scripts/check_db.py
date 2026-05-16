"""检查数据库表结构"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import sqlite3
from backend.config import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
for tname in [t[0] for t in tables]:
    cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
    print(f"  {tname}:")
    for c in cols:
        print(f"    {c[1]} ({c[2]})")
conn.close()

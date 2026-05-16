"""Find all files with syntax errors"""
import os, subprocess

BASE = r"G:\workbuddyspace\quant-ai-trader\backend"

for root, dirs, files in os.walk(BASE):
    for f in files:
        if not f.endswith(".py"):
            continue
        filepath = os.path.join(root, f)
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
        try:
            compile(content, filepath, "exec")
        except SyntaxError as e:
            print(f"SYNTAX ERROR in {filepath}:")
            print(f"  Line {e.lineno}: {e.msg}")

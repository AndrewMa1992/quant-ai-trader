"""Fix common ruff lint issues"""
import re, os

BASE = r"G:\workbuddyspace\quant-ai-trader\backend"

# Fix one-liner colon statements: `if x: statement` -> `if x:\n    statement`
fixes = {
    os.path.join(BASE, "ai_models", "rl_agent.py"): [
        (r"(\s+)(if price <= 0): continue", r"\1\2:\n\1    continue"),
        (r"(\s+)(if abs\(trade\) < 10): continue", r"\1\2:\n\1    continue"),
    ],
    os.path.join(BASE, "ai_models", "ensemble.py"): [
        (r"(\s+)(if score <= 0): return 0\.0", r"\1\2:\n\1    return 0.0"),
    ],
    os.path.join(BASE, "ai_models", "sentiment.py"): [
        (r"(\s+)(if score > 0\.2): label = \"positive\"", r"\1\2:\n\1    label = \"positive\""),
        (r"(\s+)(elif score < -0\.2): label = \"negative\"", r"\1\2:\n\1    label = \"negative\""),
        (r"(\s+)(else): label = \"neutral\"", r"\1\2:\n\1    label = \"neutral\""),
    ],
    os.path.join(BASE, "ai_models", "trainer.py"): [
        (r"(\s+)(if df\.empty): continue", r"\1\2:\n\1    continue"),
        (r"(\s+)(if key not in processed_dict): continue", r"\1\2:\n\1    continue"),
        (r"(\s+)(if not df_dict): return", r"\1\2:\n\1    return"),
    ],
}

for filepath, patterns in fixes.items():
    if not os.path.exists(filepath):
        print(f"SKIP: {filepath}")
        continue
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    for pattern, replacement in patterns:
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            print(f"  Fixed pattern in {os.path.basename(filepath)}")
            content = new_content
        else:
            print(f"  No match in {os.path.basename(filepath)}: {pattern[:30]}")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

# Fix semicolon statements: `stmt; stmt`
semicolon_fixes = {
    os.path.join(BASE, "ai_models", "trainer.py"): [
        (r"(logger\.error\(\"特征工程失败\"\)); return", r"\1\n        return"),
        (r"(logger\.warning\(f\"样本不足 .*?\)\)); return", r"\1\n        return"),
    ],
}

for filepath, patterns in semicolon_fixes.items():
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Done!")

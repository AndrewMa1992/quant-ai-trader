"""Run ruff lint check"""
import subprocess
result = subprocess.run(
    ["python", "-m", "ruff", "check", "backend/", "--statistics"],
    capture_output=True, text=True, cwd=r"G:\workbuddyspace\quant-ai-trader"
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr[:500] if result.stderr else "")
print(f"Exit: {result.returncode}")
print(f"Errors: {len(result.stdout.split(chr(10)))} lines")

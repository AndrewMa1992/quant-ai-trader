import subprocess
import sys
import os

script = r"E:\workbuddyspace\Claw\quant-ai-trader\trading_pipeline.py"
cwd = r"E:\workbuddyspace\Claw\quant-ai-trader"

proc = subprocess.Popen(
    [sys.executable, script, "--interval", "600"],
    cwd=cwd,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL
)
print(f"LAUNCHED: PID={proc.pid}")

"""Watchdog — Start frontend only (vite dev server)"""
import subprocess
import os
import time

WORKDIR = r"E:\workbuddyspace\Claw\quant-ai-trader"
FRONTEND_DIR = os.path.join(WORKDIR, "frontend")
NODE = r"C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\node.exe"
VITE_CMD = os.path.join(FRONTEND_DIR, "node_modules", ".bin", "vite.cmd")

DETACHED = 0x00000008
NEW_GROUP = 0x00000200

env = os.environ.copy()
env["NODE_PATH"] = os.path.join(FRONTEND_DIR, "node_modules")
env["PATH"] = r"C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2;" + os.path.join(FRONTEND_DIR, "node_modules", ".bin") + ";" + env.get("PATH", "")

print(f"Starting frontend: {NODE} {VITE_CMD}")
proc = subprocess.Popen(
    [NODE, VITE_CMD, "--port", "5180", "--host", "0.0.0.0"],
    cwd=FRONTEND_DIR,
    env=env,
    creationflags=DETACHED | NEW_GROUP,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"Frontend PID: {proc.pid}")

# Wait and verify
time.sleep(20)

import urllib.request
try:
    req = urllib.request.Request("http://localhost:5180")
    resp = urllib.request.urlopen(req, timeout=5)
    print(f"Frontend 5180: HTTP {resp.status} — UP")
except Exception as e:
    print(f"Frontend 5180: DOWN — {e}")

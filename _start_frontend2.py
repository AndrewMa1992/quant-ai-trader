"""Watchdog — Start frontend using npm run dev"""
import subprocess
import os
import time

WORKDIR = r"E:\workbuddyspace\Claw\quant-ai-trader"
FRONTEND_DIR = os.path.join(WORKDIR, "frontend")
NPM_CMD = r"C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\npm.cmd"
NODE_DIR = r"C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2"

DETACHED = 0x00000008
NEW_GROUP = 0x00000200

env = os.environ.copy()
env["NODE_PATH"] = os.path.join(FRONTEND_DIR, "node_modules")
env["PATH"] = NODE_DIR + ";" + env.get("PATH", "")

# Try method 1: npm run dev
print("Method 1: npm run dev")
cmd = [NPM_CMD, "run", "dev"]
proc = subprocess.Popen(
    cmd,
    cwd=FRONTEND_DIR,
    env=env,
    creationflags=DETACHED | NEW_GROUP,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
pid = proc.pid
print(f"  PID: {pid}")
time.sleep(25)

import urllib.request
try:
    req = urllib.request.Request("http://localhost:5180")
    resp = urllib.request.urlopen(req, timeout=5)
    print(f"Frontend 5180: HTTP {resp.status} — UP")
except Exception as e:
    print(f"Frontend 5180: DOWN — {e}")
    # Method 2: node directly on vite.js
    print("\nMethod 2: node vite.js directly")
    VITE_JS = os.path.join(FRONTEND_DIR, "node_modules", "vite", "bin", "vite.js")
    cmd2 = [r"C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\node.exe", VITE_JS, "--port", "5180", "--host", "0.0.0.0"]
    proc2 = subprocess.Popen(
        cmd2,
        cwd=FRONTEND_DIR,
        env=env,
        creationflags=DETACHED | NEW_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid2 = proc2.pid
    print(f"  PID: {pid2}")
    time.sleep(25)
    try:
        req = urllib.request.Request("http://localhost:5180")
        resp = urllib.request.urlopen(req, timeout=5)
        print(f"Frontend 5180: HTTP {resp.status} — UP")
    except Exception as e2:
        print(f"Frontend 5180: STILL DOWN — {e2}")

"""
Watchdog Restart All — 启动 Quant AI Trader 全部服务（独立进程，不依赖当前 session）
"""
import subprocess
import sys
import os
import time

WORKDIR = r"E:\workbuddyspace\Claw\quant-ai-trader"
PYTHON = r"C:\Users\hshor\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
NODE = r"C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\node.exe"
VITE = r"C:\Users\hshor\.workbuddy\binaries\node\workspace\node_modules\.bin\vite.cmd"

DETACHED = 0x00000008  # DETACHED_PROCESS
NEW_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP

env = os.environ.copy()
env["PYTHONPATH"] = WORKDIR
env["TORCH_HOME"] = os.path.join(WORKDIR, "cache", "torch")
env["HF_HOME"] = os.path.join(WORKDIR, "cache", "huggingface")
env["HUGGINGFACE_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# --- 7 Backend Microservices ---
services = [
    (8001, "api_gateway.main:app"),
    (8011, "services.data_service.main:app"),
    (8012, "services.factor_service.main:app"),
    (8013, "services.model_train_service.main:app"),
    (8014, "services.model_infer_service.main:app"),
    (8015, "services.risk_service.main:app"),
    (8016, "services.execution_service.main:app"),
]

print("=== Starting 7 Backend Microservices ===")
for port, module in services:
    cmd = [PYTHON, "-m", "uvicorn", module, "--host", "0.0.0.0", "--port", str(port)]
    proc = subprocess.Popen(
        cmd,
        cwd=WORKDIR,
        env=env,
        creationflags=DETACHED | NEW_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  Port {port}: PID {proc.pid}")
    time.sleep(3)

print("All 7 backend services launched. Waiting 15s for warmup...")
time.sleep(15)

# --- Frontend ---
print("\n=== Starting Frontend ===")
frontend_dir = os.path.join(WORKDIR, "frontend")
frontend_env = env.copy()
frontend_env["NODE_PATH"] = r"C:\Users\hshor\.workbuddy\binaries\node\workspace\node_modules"

cmd = [NODE, VITE, "--port", "5180", "--host", "0.0.0.0"]
proc = subprocess.Popen(
    cmd,
    cwd=frontend_dir,
    env=frontend_env,
    creationflags=DETACHED | NEW_GROUP,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"  Frontend: PID {proc.pid}")
time.sleep(5)

# --- Trading Pipeline ---
print("\n=== Starting Trading Pipeline ===")
cmd = [PYTHON, "trading_pipeline.py", "--interval", "600"]
proc = subprocess.Popen(
    cmd,
    cwd=WORKDIR,
    env=env,
    creationflags=DETACHED | NEW_GROUP,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
trading_pid = proc.pid
print(f"  Trading Pipeline: PID {trading_pid}")
time.sleep(8)

# --- Verify Trading Pipeline survived ---
import ctypes
kernel32 = ctypes.windll.kernel32
SYNCHRONIZE = 0x00100000
handle = kernel32.OpenProcess(SYNCHRONIZE, False, trading_pid)
if handle:
    ret = kernel32.WaitForSingleObject(handle, 0)
    kernel32.CloseHandle(handle)
    if ret == 0:  # WAIT_OBJECT_0 — process exited
        print(f"  WARNING: Trading Pipeline PID {trading_pid} appears to have exited!")
    else:
        print(f"  Trading Pipeline PID {trading_pid} still alive — OK")
else:
    print(f"  Trading Pipeline PID {trading_pid} — cannot open handle (may be OK)")

print("\n=== All services launched. Final health check in 20s ===")
time.sleep(20)

# Health check
import urllib.request
print("\n--- Health Check Results ---")
for port, module in services:
    try:
        req = urllib.request.Request(f"http://localhost:{port}/health")
        resp = urllib.request.urlopen(req, timeout=5)
        print(f"  Port {port}: HTTP {resp.status} — UP")
    except Exception as e:
        print(f"  Port {port}: DOWN — {e}")

try:
    req = urllib.request.Request("http://localhost:5180")
    resp = urllib.request.urlopen(req, timeout=5)
    print(f"  Frontend 5180: HTTP {resp.status} — UP")
except Exception as e:
    print(f"  Frontend 5180: DOWN — {e}")

print("\nDone.")

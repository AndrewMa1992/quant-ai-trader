#!/usr/bin/env python3
"""
Quant AI Trader — macOS 守护进程 (Watchdog)
监控 backend (FastAPI) 和 auto_trader 进程，被杀后自动重启。
"""

import os
import sys
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
PROJ_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJ_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

PYTHON = "/opt/miniconda3/envs/quant/bin/python"
BACKEND_PORT = 8001
HEALTH_URL = f"http://localhost:{BACKEND_PORT}/health"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "watchdog.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("watchdog")

# ── Process tracking ────────────────────────────────────────
processes: dict[str, subprocess.Popen | None] = {
    "backend": None,
    "trader": None,
}
restart_counts: dict[str, int] = {"backend": 0, "trader": 0}
running = True


def start_backend() -> subprocess.Popen | None:
    """启动 FastAPI 后端"""
    cmd = [PYTHON, str(PROJ_ROOT / "run_backend.py")]
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(PROJ_ROOT),
            stdout=open(LOG_DIR / "backend.log", "a"),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        logger.info(f"Backend started (PID={p.pid})")
        return p
    except Exception as e:
        logger.error(f"Backend start failed: {e}")
        return None


def start_trader() -> subprocess.Popen | None:
    """启动自动交易引擎"""
    cmd = [PYTHON, str(PROJ_ROOT / "auto_trader.py"), "--interval", "300"]
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(PROJ_ROOT),
            stdout=open(LOG_DIR / "trader.log", "a"),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        logger.info(f"AutoTrader started (PID={p.pid})")
        return p
    except Exception as e:
        logger.error(f"AutoTrader start failed: {e}")
        return None


def check_backend_health() -> bool:
    """HTTP 健康检查"""
    try:
        import urllib.request
        req = urllib.request.Request(HEALTH_URL)
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status == 200
    except Exception:
        return False


def check_process_alive(proc: subprocess.Popen | None) -> bool:
    """检查进程是否存活"""
    if proc is None:
        return False
    return proc.poll() is None


def restart_process(name: str) -> bool:
    """重启指定进程"""
    restart_counts[name] += 1
    count = restart_counts[name]

    # 快速重启保护：1分钟内超过5次则延迟
    if count > 5:
        delay = min(300, (count - 5) * 30)
        logger.warning(
            f"{name} 已重启 {count} 次，等 {delay}s 再试"
        )
        time.sleep(delay)

    old_proc = processes.get(name)
    if old_proc and old_proc.poll() is None:
        try:
            os.killpg(os.getpgid(old_proc.pid), signal.SIGTERM)
            old_proc.wait(timeout=10)
        except Exception:
            try:
                old_proc.kill()
            except Exception:
                pass

    if name == "backend":
        processes[name] = start_backend()
    elif name == "trader":
        processes[name] = start_trader()

    return processes[name] is not None


def stop_all():
    """安全停止所有进程"""
    global running
    running = False
    logger.info("Shutting down all processes...")

    for name, proc in processes.items():
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=15)
                logger.info(f"{name} stopped gracefully")
            except Exception:
                try:
                    proc.kill()
                    logger.warning(f"{name} force killed")
                except Exception:
                    pass


def signal_handler(sig, frame):
    logger.info(f"Signal {sig} received")
    stop_all()
    sys.exit(0)


# ── Main loop ──────────────────────────────────────────────
def main():
    global running

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("=" * 60)
    logger.info("Quant AI Trader Watchdog starting...")
    logger.info(f"Project: {PROJ_ROOT}")
    logger.info(f"Python:  {PYTHON}")
    logger.info("=" * 60)

    # 启动进程
    processes["backend"] = start_backend()
    time.sleep(3)  # 等 backend 启动
    processes["trader"] = start_trader()

    # 健康检查 interval
    health_interval = 30    # 每 30s 检查一次
    trader_interval = 60    # 每 60s 检查一次
    last_health_check = time.time()
    last_trader_check = time.time()

    while running:
        time.sleep(5)  # 主循环 tick

        now = time.time()

        # Backend 健康检查
        if now - last_health_check >= health_interval:
            last_health_check = now
            proc = processes["backend"]
            alive = check_process_alive(proc)

            if not alive:
                logger.error("Backend process died! Restarting...")
                restart_process("backend")
            elif not check_backend_health():
                logger.warning("Backend health check FAILED (port alive but /health not 200)")
                # 仍然尝试 restart
                if restart_counts["backend"] % 10 == 0:
                    logger.warning("Health check failures persistent, restarting backend")
                    restart_process("backend")
            else:
                restart_counts["backend"] = max(0, restart_counts["backend"] - 1)

        # AutoTrader 存活检查
        if now - last_trader_check >= trader_interval:
            last_trader_check = now
            proc = processes["trader"]

            if not check_process_alive(proc):
                logger.error("AutoTrader process died! Restarting...")
                restart_process("trader")
            else:
                restart_counts["trader"] = max(0, restart_counts["trader"] - 1)

        # 状态汇总（每 5 分钟）
        if int(now) % 300 < 5:
            status = {
                "time": datetime.now().isoformat(),
                "backend": "alive" if check_process_alive(processes["backend"]) else "DEAD",
                "trader": "alive" if check_process_alive(processes["trader"]) else "DEAD",
                "restarts": dict(restart_counts),
            }
            logger.info(f"Status: {status}")


if __name__ == "__main__":
    main()

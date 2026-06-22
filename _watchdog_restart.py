"""Watchdog restart script — launch frontend + trading pipeline as detached processes."""
import subprocess, os, time, sys

project_dir = r'E:\workbuddyspace\Claw\quant-ai-trader'
managed_python = r'C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe'
managed_npm = r'C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\npm.cmd'

results = {}

# 1. Start Trading Pipeline
print('[1/2] Starting Trading Pipeline...')
tp = subprocess.Popen(
    [managed_python, 'trading_pipeline.py', '--interval', '600'],
    cwd=project_dir,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True
)
results['trading_pipeline'] = {'pid': tp.pid, 'status': 'launched'}
print(f'  Trading Pipeline launched (PID={tp.pid})')

# 2. Start Frontend (npm run dev)
print('[2/2] Starting Frontend (npm run dev)...')
fe = subprocess.Popen(
    [managed_npm, 'run', 'dev'],
    cwd=os.path.join(project_dir, 'frontend'),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True
)
results['frontend'] = {'pid': fe.pid, 'status': 'launched'}
print(f'  Frontend launched (PID={fe.pid})')

# Wait and verify
print()
print('Waiting 8s for services to start...')
time.sleep(8)

# Verify Trading Pipeline
wmi_check = subprocess.run(['powershell', '-Command',
    r'Get-WmiObject Win32_Process -Filter "Name=\'python.exe\'" | Where-Object { $_.CommandLine -match "trading_pipeline" } | Select-Object -ExpandProperty ProcessId'
], capture_output=True, text=True, timeout=15)
tp_pids = [l.strip() for l in wmi_check.stdout.strip().split('\n') if l.strip().isdigit()]
if tp_pids:
    results['trading_pipeline']['verified'] = True
    results['trading_pipeline']['pids'] = tp_pids
    print(f'  Trading Pipeline: ALIVE (PIDs: {tp_pids})')
else:
    results['trading_pipeline']['verified'] = False
    print('  Trading Pipeline: FAILED to verify')

# Verify Frontend
try:
    import urllib.request
    req = urllib.request.Request('http://localhost:5180', method='HEAD')
    resp = urllib.request.urlopen(req, timeout=5)
    results['frontend']['verified'] = True
    results['frontend']['http_status'] = resp.status
    print(f'  Frontend: ALIVE (HTTP {resp.status})')
except Exception as e:
    results['frontend']['verified'] = False
    results['frontend']['error'] = str(e)
    print(f'  Frontend: PENDING (will retry) - {e}')

print()
print('=== SUMMARY ===')
for k, v in results.items():
    print(f'{k}: {v}')

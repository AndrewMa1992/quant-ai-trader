import subprocess, os, time, sys

project = r'E:\workbuddyspace\Claw\quant-ai-trader'
npm_cmd = r'C:\Users\hshor\.workbuddy\binaries\node\versions\22.22.2\npm.cmd'
python = r'C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe'

results = {}

# 1. Start Trading Pipeline
print('[1/2] Launching trading_pipeline.py (interval=600)...')
tp = subprocess.Popen(
    [python, 'trading_pipeline.py', '--interval', '600'],
    cwd=project,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
)
results['trading_pipeline'] = {'pid': tp.pid}
print(f'  PID: {tp.pid}')

# 2. Start Frontend
print('[2/2] Launching frontend (npm run dev)...')
fe = subprocess.Popen(
    [npm_cmd, 'run', 'dev'],
    cwd=os.path.join(project, 'frontend'),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
)
results['frontend'] = {'pid': fe.pid}
print(f'  PID: {fe.pid}')

print()
print('Waiting 8s for services to initialize...')
time.sleep(8)

# Verify Trading Pipeline
tp_ok = False
try:
    wmi_cmd = 'Get-WmiObject Win32_Process -Filter "Name=\'python.exe\'" | Select-Object ProcessId, CommandLine | ForEach-Object { Write-Output "$($_.ProcessId): $($_.CommandLine)" }'
    wmi_out = subprocess.check_output(
        ['powershell', '-Command', wmi_cmd],
        timeout=15
    ).decode('utf-8', errors='replace')
    if 'trading_pipeline.py --interval 600' in wmi_out:
        print(f'[OK] Trading Pipeline alive (interval=600)')
        tp_ok = True
    else:
        print(f'[WARN] Trading Pipeline not confirmed')
        print(f'WMI check: {wmi_out[:500]}')
except Exception as e:
    print(f'[WARN] WMI check error: {e}')

# Verify Frontend
fe_ok = False
try:
    import urllib.request
    r = urllib.request.urlopen('http://localhost:5180', timeout=5)
    code = r.getcode()
    if code == 200:
        print(f'[OK] Frontend HTTP {code}')
        fe_ok = True
    else:
        print(f'[WARN] Frontend HTTP {code}')
except Exception as e:
    print(f'[WARN] Frontend not responding: {e}')

print()
print('=== SUMMARY ===')
print(f'Trading Pipeline: {"OK" if tp_ok else "NEEDS CHECK"} (PID {results["trading_pipeline"]["pid"]})')
print(f'Frontend:         {"OK" if fe_ok else "NEEDS CHECK"} (PID {results["frontend"]["pid"]})')

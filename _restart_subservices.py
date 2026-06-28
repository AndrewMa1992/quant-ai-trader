import subprocess, time, os

project = r'E:\workbuddyspace\Claw\quant-ai-trader'
python = r'C:\Users\hshor\.workbuddy\binaries\python\versions\3.13.12\python.exe'

services = [
    ('factor',      8012, 'services.factor_service.main:app'),
    ('model_train', 8013, 'services.model_train_service.main:app'),
    ('model_infer', 8014, 'services.model_infer_service.main:app'),
    ('risk',        8015, 'services.risk_service.main:app'),
    ('execution',   8016, 'services.execution_service.main:app'),
]

pids = []

for name, port, module in services:
    print(f'Starting {name} on port {port}...')
    proc = subprocess.Popen(
        [python, '-m', 'uvicorn', module, '--host', '0.0.0.0', '--port', str(port)],
        cwd=project,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    )
    pids.append((name, port, proc.pid))
    print(f'  {name}({port}): PID {proc.pid}')

print()
print('Waiting 10s for services to initialize...')
time.sleep(10)

# Verify
import urllib.request
ok, fail = 0, 0
for name, port, pid in pids:
    try:
        r = urllib.request.urlopen(f'http://localhost:{port}/health', timeout=5)
        print(f'[OK] {name}({port}): HTTP {r.getcode()}')
        ok += 1
    except Exception as e:
        print(f'[FAIL] {name}({port}): {type(e).__name__}')
        fail += 1

print(f'\n=== SUB-SERVICES: {ok} OK, {fail} FAIL ===')

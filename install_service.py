"""Install runner as Windows service"""
import subprocess, os

RUNNER_DIR = r"G:\workbuddyspace\actions-runner"

# The runner has a built-in service install via config.cmd
# But some versions need the .nssm approach

# Check if run.cmd supports --svc
result = subprocess.run(
    [os.path.join(RUNNER_DIR, "run.cmd"), "--help"],
    capture_output=True, text=True, cwd=RUNNER_DIR, timeout=30
)
output = result.stdout + result.stderr

if "start" in output.lower() or "svc" in output.lower():
    print("Found service support in run.cmd")
else:
    print("No --svc flag found. Trying alternative method.")

# Use the .nssm service manager bundled with the runner  
nssm = os.path.join(RUNNER_DIR, "bin", "Runner.Service.exe")
if os.path.exists(nssm):
    print(f"Found Runner.Service.exe")
else:
    print("No Runner.Service.exe. Trying direct service create.")
    
    # Try creating service via sc.exe
    svc_result = subprocess.run(
        ["sc.exe", "create", "QuantAITraderRunner",
         "binPath=", f'"{os.path.join(RUNNER_DIR, "run.cmd")}"',
         "start=", "auto",
         "DisplayName=", "Quant AI Trader - GitHub Runner"],
        capture_output=True, text=True, timeout=30
    )
    print(f"sc create: {svc_result.returncode}")
    print(svc_result.stdout)
    print(svc_result.stderr)
    
    if svc_result.returncode == 0:
        # Start service
        subprocess.run(["sc.exe", "start", "QuantAITraderRunner"], timeout=30)
        print("Service started!")

"""Install GitHub self-hosted runner in workspace"""
import subprocess, os, json, urllib.request

TOKEN = "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"
WORKSPACE = r"G:\workbuddyspace"
RUNNER_DIR = os.path.join(WORKSPACE, "actions-runner")
REPO = "AndrewMa1992/quant-ai-trader"

# 1. Get registration token from API
print("Getting runner registration token...")
req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/actions/runners/registration-token",
    method="POST",
    headers={"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"}
)
resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
reg_token = resp["token"]
print(f"Token: {reg_token[:8]}... (expires: {resp['expires_at']})")

# 2. Download runner
if not os.path.exists(RUNNER_DIR):
    os.makedirs(RUNNER_DIR)
os.chdir(RUNNER_DIR)

runner_url = "https://github.com/actions/runner/releases/download/v2.320.0/actions-runner-win-x64-2.320.0.zip"
zip_path = os.path.join(RUNNER_DIR, "runner.zip")

if not os.path.exists(os.path.join(RUNNER_DIR, "config.cmd")):
    print(f"\nDownloading runner...")
    urllib.request.urlretrieve(runner_url, zip_path)
    print("Extracting...")
    import zipfile
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(RUNNER_DIR)
    os.remove(zip_path)
    print("Extracted.")
else:
    print("Runner already downloaded.")

# 3. Configure
print("\nConfiguring runner...")
config_result = subprocess.run(
    [os.path.join(RUNNER_DIR, "config.cmd"),
     "--url", f"https://github.com/{REPO}",
     "--token", reg_token,
     "--name", "quant-trader-gpu",
     "--labels", "gpu,windows",
     "--work", os.path.join(WORKSPACE, "quant-ai-trader", ".github", "runner-work"),
     "--unattended"],  # unattended = no prompts
    capture_output=True, text=True, timeout=120
)
print(config_result.stdout[-500:] if config_result.stdout else "")
print(config_result.stderr[-500:] if config_result.stderr else "")
print(f"Config exit: {config_result.returncode}")

# 4. Install as Windows service (may need admin)
if config_result.returncode == 0:
    print("\nInstalling as Windows service...")
    svc_result = subprocess.run(
        [os.path.join(RUNNER_DIR, "svc.cmd"), "install"],
        capture_output=True, text=True, timeout=60
    )
    print(svc_result.stdout[-500:] if svc_result.stdout else "")
    print(svc_result.stderr[-500:] if svc_result.stderr else "")
    print(f"Service install exit: {svc_result.returncode}")

    # Start service
    print("\nStarting service...")
    start_result = subprocess.run(
        [os.path.join(RUNNER_DIR, "svc.cmd"), "start"],
        capture_output=True, text=True, timeout=30
    )
    print(start_result.stdout[-300:] if start_result.stdout else "")
    print(start_result.stderr[-300:] if start_result.stderr else "")
else:
    print("\nConfig failed. Trying svc.cmd might need admin rights.")
    print("You may need to run this manually:")
    print(f"  cd {RUNNER_DIR}")
    print(f"  .\svc.cmd install")
    print(f"  .\svc.cmd start")

print("\nDone! Check GitHub: https://github.com/AndrewMa1992/quant-ai-trader/settings/actions/runners")

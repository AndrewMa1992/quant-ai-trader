"""Push final commit to GitHub via API"""
import subprocess, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
token = "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"
owner = "AndrewMa1992"
repo = "quant-ai-trader"

# Get the local commit we need to push
result = subprocess.run(
    [r"C:\Program Files\Git\bin\git.exe", "rev-parse", "HEAD"],
    capture_output=True, text=True, cwd=os.getcwd()
)
local_head = result.stdout.strip()
print(f"Local HEAD: {local_head[:8]}")

# Get the remote HEAD
import urllib.request
url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/main"
req = urllib.request.Request(url, headers={"Authorization": f"token {token}"})
try:
    resp = urllib.request.urlopen(req, timeout=15)
    import json
    remote = json.loads(resp.read())
    remote_head = remote["object"]["sha"]
    print(f"Remote HEAD: {remote_head[:8]}")
except Exception as e:
    print(f"Remote error: {e}")
    remote_head = None

if local_head == remote_head:
    print("Already up to date!")
else:
    print("Need to push...")
    # Find commits between remote and local
    result = subprocess.run(
        [r"C:\Program Files\Git\bin\git.exe", "log", f"{remote_head or '--root'}..HEAD", "--oneline"],
        capture_output=True, text=True, cwd=os.getcwd()
    )
    print(f"Commits to push:\n{result.stdout}")
    print(f"\nUse curl or git in a new terminal window:")
    print(f"  cd G:\\workbuddyspace\\quant-ai-trader")
    print(f"  git push origin main --force")

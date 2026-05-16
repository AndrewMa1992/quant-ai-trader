"""Check GitHub Actions runs"""
import json, urllib.request
token = "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"
req = urllib.request.Request(
    "https://api.github.com/repos/AndrewMa1992/quant-ai-trader/actions/runs?per_page=5",
    headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
)
resp = urllib.request.urlopen(req, timeout=15)
data = json.loads(resp.read())
runs = data.get("workflow_runs", [])
if runs:
    for r in runs:
        print(f"  {r['name']}: {r['status']} ({r['conclusion'] or 'running...'})")
else:
    print("  No workflow runs yet (may take a moment)")

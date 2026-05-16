"""Check GitHub runner status"""
import json, urllib.request
token = "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"
req = urllib.request.Request(
    "https://api.github.com/repos/AndrewMa1992/quant-ai-trader/actions/runners",
    headers={"Authorization": f"token {token}"}
)
data = json.loads(urllib.request.urlopen(req).read())
runners = data.get("runners", [])
if runners:
    for r in runners:
        print(f"  {r['name']}: status={r['status']}, busy={r.get('busy',False)}")
else:
    print("  No runners found")

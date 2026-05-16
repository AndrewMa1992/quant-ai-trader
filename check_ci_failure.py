"""Get GitHub Actions CI failure logs"""
import json, urllib.request
token = "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"
headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

# Get latest CI run
req = urllib.request.Request(
    "https://api.github.com/repos/AndrewMa1992/quant-ai-trader/actions/runs?per_page=5",
    headers=headers
)
runs = json.loads(urllib.request.urlopen(req, timeout=15).read())

for run in runs["workflow_runs"]:
    if "CI" in run["name"] and run["conclusion"] == "failure":
        print(f"CI Run: {run['id']} ({run['status']}/{run['conclusion']})")
        print(f"Branch: {run['head_branch']}")
        print(f"Commit: {run['head_sha'][:8]}")
        print(f"URL: {run['html_url']}")
        print()
        
        # Get jobs
        jobs_url = run["jobs_url"]
        req2 = urllib.request.Request(jobs_url, headers=headers)
        jobs = json.loads(urllib.request.urlopen(req2, timeout=15).read())
        
        for job in jobs["jobs"]:
            print(f"Job: {job['name']} ({job['conclusion']})")
            for step in job["steps"]:
                icon = "✅" if step["conclusion"] == "success" else "❌" if step["conclusion"] == "failure" else "⏳"
                print(f"  {icon} {step['name']}: {step['conclusion'] or step['status']}")
                if step["conclusion"] == "failure":
                    # Get logs
                    log_url = f"https://api.github.com/repos/AndrewMa1992/quant-ai-trader/actions/jobs/{job['id']}/logs"
                    try:
                        req3 = urllib.request.Request(log_url, headers=headers)
                        logs = urllib.request.urlopen(req3, timeout=15).read().decode()
                        # Get last 20 lines
                        lines = logs.strip().split("\n")
                        print(f"  --- Last 10 lines of log ---")
                        for line in lines[-10:]:
                            print(f"  {line[:200]}")
                    except Exception as e:
                        print(f"  Error getting logs: {e}")
        break

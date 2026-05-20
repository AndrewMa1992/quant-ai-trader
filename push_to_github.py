"""Push to GitHub using clean environment"""
import subprocess, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
clean_env = {k: v for k, v in os.environ.items()
             if k.lower() not in ("http_proxy", "https_proxy")}

result = subprocess.run(
    [r"C:\Program Files\Git\bin\git.exe", "push", "origin", "main", "--force"],
    capture_output=True, text=True, timeout=120, env=clean_env
)
print(f"Exit: {result.returncode}")
if result.stdout: print(result.stdout)
if result.stderr: print(result.stderr)
print("SUCCESS" if result.returncode == 0 else "FAILED")

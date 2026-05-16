"""Push to GitHub, bypassing system proxy"""
import subprocess, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Create a clean environment without proxy vars
clean_env = {k: v for k, v in os.environ.items() 
             if k.lower() not in ("http_proxy", "https_proxy")}

result = subprocess.run(
    [r"C:\Program Files\Git\bin\git.exe", "push", "origin", "main", "--force"],
    capture_output=True, text=True, timeout=120,
    env=clean_env
)
print(f"Exit code: {result.returncode}")
print(f"STDOUT: {result.stdout}")
print(f"STDERR: {result.stderr}")

if result.returncode == 0:
    print("\n✅ PUSH SUCCESS!")
else:
    print("\n❌ PUSH FAILED")
    print("Try manually in a new PowerShell window:")
    print("  cd G:\\workbuddyspace\\quant-ai-trader")
    print("  git push origin main --force")

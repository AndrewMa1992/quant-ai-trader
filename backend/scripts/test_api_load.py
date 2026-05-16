"""验证 FastAPI 应用能正常加载"""
import sys
sys.path.insert(0, '.')

# 这不会启动服务器，只是验证应用对象能被创建
from backend.main import app

print(f"FastAPI app: {app.title} v{app.version}")
print(f"Routes ({len(app.routes)}):")
for route in app.routes:
    if hasattr(route, 'path') and hasattr(route, 'methods'):
        methods = ','.join(route.methods - {'HEAD', 'OPTIONS'})
        if methods:
            print(f"  {methods:8s} {route.path}")
    elif hasattr(route, 'path'):
        print(f"  WS        {route.path}")

print("\nApp loaded successfully!")

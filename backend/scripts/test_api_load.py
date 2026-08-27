"""Verify that the FastAPI application loads successfully."""
import sys
sys.path.insert(0, '.')

# Does not start the server; only verifies that the app object can be created.
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

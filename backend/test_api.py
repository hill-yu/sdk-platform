import sys, json
sys.path.insert(0, '.')
from app.core.config import get_settings
import subprocess

token = get_settings().ADMIN_TOKEN
bh = "Bearer " + str(token)

endpoints = [
    ("dashboard/summary", ""),
    ("dashboard/trend", "?range=7d"),
    ("dashboard/breakdown", "?dimension=event_type"),
    ("events", "?page=1&page_size=5"),
]

for ep, qs in endpoints:
    url = f"http://localhost:8101/api/admin/{ep}{qs}"
    cp = subprocess.run(
        ['curl', '-s', url, '-H', bh],
        capture_output=True, text=True
    )
    print(f"\n=== {ep}{qs} ===")
    try:
        print(json.dumps(json.loads(cp.stdout), indent=2, ensure_ascii=False))
    except Exception:
        print(cp.stdout[:300])

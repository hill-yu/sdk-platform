import sys, json, asyncio
sys.path.insert(0, '.')
from app.core.config import get_settings
import httpx

async def main():
    settings = get_settings()
    base = "http://localhost:8101/api/admin"
    headers = {"Authorization": "Bearer " + settings.ADMIN_TOKEN}
    
    async with httpx.AsyncClient() as client:
        endpoints = [
            ("dashboard/summary", ""),
            ("dashboard/trend", "?range=7d"),
            ("dashboard/breakdown", "?dimension=event_type"),
            ("events", "?page=1&page_size=5"),
        ]
        for ep, qs in endpoints:
            url = f"{base}/{ep}{qs}"
            resp = await client.get(url, headers=headers)
            print(f"\n=== {ep}{qs} (status={resp.status_code}) ===")
            try:
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
            except Exception:
                print(resp.text[:300])

asyncio.run(main())

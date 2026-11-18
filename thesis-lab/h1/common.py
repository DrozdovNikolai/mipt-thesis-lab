import json
import os
from pathlib import Path
import time
import httpx
import asyncio

OUT = Path(os.environ.get('THESIS_OUTPUT', '/results/h1-local-development'))
OUT.mkdir(parents=True, exist_ok=True)
BACKEND = os.environ.get('H1_BACKEND_URL', 'http://functional:8000')
PROXY = os.environ.get('H1_PROXY_URL', 'http://proxy:8001')

def append(name, value):
    with (OUT / name).open('a') as f:
        f.write(json.dumps({'recorded_at': time.time(), **value}, ensure_ascii=False, default=str)+'\n')

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n')

def client():
    return httpx.AsyncClient(base_url=BACKEND, timeout=120)

async def login(c):
    for _ in range(120):
        try:
            if (await c.get('/')).status_code == 200: break
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.5)
    r = await c.post('/api/auth/login', json={'login':'admin', 'password':os.environ.get('ADMIN_PASSWORD','admin123')})
    r.raise_for_status()
    return {'Authorization': 'Bearer '+r.json()['accessToken']}

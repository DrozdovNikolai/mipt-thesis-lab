"""Bounded retained-read comparison on a dedicated, static synthetic database."""
import asyncio
import hashlib
import json
import statistics
from pathlib import Path
from time import perf_counter

import httpx

paths = ['/api/training/competences', '/api/training/scenarios']


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


async def main():
    clients = [httpx.AsyncClient(base_url=base, timeout=30) for base in
               ['http://baseline-api:8000', 'http://benchmark-api:8000']]
    try:
        headers = []
        for client in clients:
            response = await client.post('/api/auth/login', json={'login': 'admin', 'password': 'admin123'})
            assert response.status_code == 200
            headers.append({'Authorization': 'Bearer ' + response.json()['accessToken']})
        expected = {}
        for path in paths:
            replies = [await client.get(path, headers=header) for client, header in zip(clients, headers)]
            assert all(reply.status_code == 200 for reply in replies), path
            assert replies[0].json() == replies[1].json(), path
            expected[path] = signature(replies[0].json())
        batches = []
        for concurrency in [1, 4, 16]:
            for kind, client, header in zip(['baseline', 'candidate'], clients, headers):
                semaphore = asyncio.Semaphore(concurrency)
                samples = []
                failures = []

                async def request(index):
                    path = paths[index % len(paths)]
                    async with semaphore:
                        started = perf_counter()
                        try:
                            response = await client.get(path, headers=header)
                            assert response.status_code == 200
                            assert signature(response.json()) == expected[path]
                            samples.append((perf_counter() - started) * 1000)
                        except Exception as exc:
                            failures.append({'path': path, 'type': type(exc).__name__})

                started = perf_counter()
                await asyncio.gather(*(request(index) for index in range(128)))
                elapsed = perf_counter() - started
                assert len(samples) == 128 and not failures, (kind, concurrency, failures)
                ordered = sorted(samples)
                batches.append({'kind': kind, 'concurrency': concurrency, 'requests': len(samples),
                                'elapsed_seconds': elapsed, 'requests_per_second': len(samples) / elapsed,
                                'median_ms': statistics.median(samples), 'p95_ms': ordered[121],
                                'max_ms': max(samples), 'failures': len(failures)})
        report = {'status': 'passed', 'requests': sum(row['requests'] for row in batches),
                  'paths': paths, 'response_sha256': expected, 'batches': batches,
                  'scope': 'One bounded sequential batch per service and concurrency level on the same static synthetic PostgreSQL and Docker host. Metrics/logging enabled, rate limiting/Sentry disabled. Checks successful identical decoded JSON on every request. Client-side latency includes HTTP and JSON work. No repetition, production-sized dataset, write/rollback/media/S3 load or production capacity claim.'}
        Path('/results/release-read-benchmark.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'status': 'passed', 'requests': report['requests'], 'batches': batches}))
    finally:
        for client in clients:
            await client.aclose()


asyncio.run(main())

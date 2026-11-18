"""Separate crashable process consuming the same durable journal for all variants."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import httpx
from h1.common import PROXY, append
from h1.journal import connect, receipt_matches

async def main(config):
    db = connect(Path(config['queue']))
    expected_json, frozen, digest = db.execute('SELECT expected,submit_body,sha256 FROM intent').fetchone()
    assert hashlib.sha256(frozen.encode()).hexdigest() == digest
    expected = json.loads(expected_json)
    ctx = {'case_id':config['case_id'], 'pid':os.getpid()}
    append('client-processes.jsonl', {**ctx,'event':'start'})
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=10) as c:
        attempt = 0
        while row := db.execute('SELECT id,path,body,sha256 FROM queue ORDER BY id LIMIT 1').fetchone():
            if time.monotonic() > config.get('deadline', started+120):
                raise TimeoutError('Delivery exceeded 120 seconds')
            qid,path,body,body_hash = row
            assert hashlib.sha256(body.encode()).hexdigest() == body_hash
            if path.endswith('/submit'):
                assert body == frozen
            attempt += 1
            t = time.perf_counter()
            record = {**ctx,'queue_id':qid,'path':path,'attempt':attempt,'request_hash':body_hash}
            try:
                r = await c.post(PROXY+path, content=body.encode(),
                    headers={**config['headers'],'Content-Type':'application/json'})
                record['status'] = r.status_code
                if r.status_code >= 500:
                    raise httpx.TransportError('Backend temporarily unavailable')
                r.raise_for_status()
                if path.endswith('/submit') and not receipt_matches(r.json(), expected):
                    record['invalid_receipt'] = True
                    raise httpx.TransportError('Receipt does not prove frozen intent')
                if config.get('crash') == 'after_submit' and path.endswith('/submit'):
                    append('client-attempts.jsonl', {**record,'point':'before_local_receipt_commit',
                        'ms':(time.perf_counter()-t)*1000})
                    os._exit(77)
                with db:
                    if path.endswith('/submit'):
                        db.execute('INSERT INTO receipt VALUES(1,?,?)',(r.text,time.time()))
                    db.execute('DELETE FROM queue WHERE id=?',(qid,))
                if path.endswith('/submit'):
                    append('receipts-accepted.jsonl',{**ctx,'accepted_at':time.time(),
                        'accepted_perf_counter':time.perf_counter(), 'manifest':expected['manifest']})
                record['accepted'] = True
            except httpx.TransportError as error:
                record['error'] = type(error).__name__
                append('client-attempts.jsonl',{**record,'ms':(time.perf_counter()-t)*1000})
                if config.get('crash') == 'offline':
                    os._exit(77)
                await asyncio.sleep(min(1.0, 0.25 * attempt))
                continue
            append('client-attempts.jsonl',{**record,'ms':(time.perf_counter()-t)*1000})
            attempt = 0
    assert db.execute('SELECT COUNT(*) FROM receipt').fetchone()[0] == 1
    db.close()
    append('client-processes.jsonl',{**ctx,'event':'completed'})

if __name__ == '__main__':
    asyncio.run(main(json.load(sys.stdin)))

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
import httpx
from h1.common import OUT, PROXY, client, login, append, save
from h1.journal import create, connect, receipt_matches
from h1.verify import compare

VARIANTS = ['split_full','split_compact','unified_compact']
FAULTS = ['offline_restart','sync_ack_loss','submit_ack_loss','client_crash_after_submit','server_crash_before_commit']
NETWORKS = [(0,0),(80,512),(250,64)]

def matrix(reps=8, smoke=False):
    rows = []
    for rep in range(reps):
        cells = [(cache,network,gzip,'clean') for cache in (1024,16384)
                 for network in NETWORKS for gzip in (False,True)]
        cells += [(cache,network,True,fault) for cache in (1024,16384)
                  for network in NETWORKS[1:] for fault in FAULTS]
        if smoke:
            cells = [(1024,(0,0),True,f) for f in ['clean',*FAULTS,'invalid_receipt']]
        random.Random(20261004+rep).shuffle(cells)
        for cell_index,(cache,network,gzip,fault) in enumerate(cells):
            variants = list(VARIANTS)
            random.Random(20261004+rep*100+cell_index).shuffle(variants)
            for variant in variants:
                rows.append(dict(rep=rep,cache=cache,rtt_ms=network[0],kib_s=network[1],
                                 gzip=gzip,fault=fault,variant=variant))
    return rows

async def worker(config):
    process = await asyncio.create_subprocess_exec(sys.executable,'-m','h1.delivery',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(config).encode()),130)
    except asyncio.TimeoutError:
        process.kill(); await process.wait(); return -9, process.pid, 'supervisor timeout'
    # Requests carry auth in headers; never print or store config or response bodies on failure.
    if stderr:
        append('client-errors.jsonl', {'case_id':config['case_id'],'error':stderr.decode()[-6000:]})
    return process.returncode, process.pid, stderr.decode()[-500:]

async def control(c, **settings):
    r = await c.post(PROXY+'/_control',json=settings)
    r.raise_for_status()
    return r.json()

async def main(args):
    if (OUT/'start.json').exists(): raise FileExistsError('Refusing to rerun a started series')
    jobs = matrix(args.reps, args.smoke)
    if args.rep is not None: jobs = [job for job in jobs if job['rep']==args.rep]
    if args.limit: jobs = jobs[:args.limit]
    save('matrix.json',jobs)
    save('start.json', {'at':time.time(),'plan_sha256':hashlib.sha256(Path('/lab/h1/PLAN.md').read_bytes()).hexdigest(),
                        'smoke':args.smoke,'count':len(jobs)})
    async with client() as c:
        headers = await login(c)
        for index, job in enumerate(jobs):
            case_id = f'{index:04d}-r{job["rep"]}-{job["variant"]}-{job["fault"]}'
            fixture_response = await c.post('/_h1/fixture',headers=headers,
                json={'variant':job['variant'],'cache':job['cache']})
            fixture_response.raise_for_status()
            fixture = fixture_response.json()
            queue = OUT / (case_id+'.sqlite')
            create(queue,fixture)
            save(case_id+'-fixture.json',fixture)
            config = {'queue':str(queue),'case_id':case_id,'headers':headers}
            await control(c,rtt_ms=job['rtt_ms'],kib_s=job['kib_s'],gzip=job['gzip'],
                offline=False,drop_next=False,drop_path='',offline_after_drop=False,corrupt_receipt=False,
                label=case_id,reset_events=True)
            fault = job['fault']
            codes, pids = [], []
            fault_before = None
            if fault == 'offline_restart':
                await control(c,offline=True)
                code,pid,_ = await worker({**config,'crash':'offline'})
                codes.append(code);pids.append(pid)
                assert code == 77
                # Restoration boundary precedes new client process startup.
                await control(c,offline=False)
            elif fault in ('sync_ack_loss','submit_ack_loss'):
                path = '/submit' if fault=='submit_ack_loss' else ('/draft' if job['variant']=='split_full' else '/sync')
                await control(c,drop_next=True,drop_path=path)
            elif fault == 'server_crash_before_commit':
                r = await c.post('/_h1/arm',headers=headers,json={'training_id':fixture['training_id']})
                r.raise_for_status();fault_before=r.json()
            elif fault == 'invalid_receipt':
                await control(c,corrupt_receipt=True)
            started_at = time.time(); started = time.perf_counter()
            config['deadline'] = time.monotonic()+120
            code,pid,error = await worker({**config,'crash':'after_submit' if fault=='client_crash_after_submit' else None})
            codes.append(code);pids.append(pid)
            if fault=='client_crash_after_submit' and code==77:
                code,pid,error = await worker(config)
                codes.append(code);pids.append(pid)
            delivery_ms = (time.perf_counter()-started)*1000
            ended_at = time.time()
            accepted_file = OUT/'receipts-accepted.jsonl'
            accepted = [json.loads(line) for line in accepted_file.read_text().splitlines()
                        if json.loads(line)['case_id']==case_id] if accepted_file.exists() else []
            if accepted:
                assert len(accepted)==1
                delivery_ms = (accepted[0]['accepted_perf_counter']-started)*1000
                ended_at = accepted[0]['accepted_at']
            # Synchronize with proxy after its final write before reading counters.
            await asyncio.sleep(0.03)
            traffic = (await control(c))['events']
            fault_after = (await c.get('/_h1/instance',headers=headers)).json()
            checked = await c.get(f'/_h1/check/{fixture["training_id"]}',headers=headers)
            checked.raise_for_status();actual=checked.json()
            issues = compare(actual,fixture['expected'])
            db=connect(queue)
            receipts=db.execute('SELECT body,accepted_at FROM receipt').fetchall()
            remaining=db.execute('SELECT count(*) FROM queue').fetchone()[0]
            if len(receipts)!=1 or not receipt_matches(json.loads(receipts[0][0]),fixture['expected']): issues.append('local_receipt')
            if remaining or code: issues.append('unfinished_delivery')
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.close()
            lost = [x for x in traffic if x.get('dropped')=='after_backend_response']
            injected = fault=='clean' or (
                fault=='offline_restart' and 77 in codes and any(x.get('dropped')=='before_forward' for x in traffic)) or (
                fault in ('sync_ack_loss','submit_ack_loss') and len(lost)==1) or (
                fault=='client_crash_after_submit' and codes==[77,0] and len(set(pids))==2) or (
                fault=='server_crash_before_commit' and fault_before['instance']!=fault_after['instance'] and
                fault_after['last_rollback']['passed'] and
                fault_after['last_rollback']['training_id']==fixture['training_id'] and
                any(x.get('dropped')=='upstream_transport' for x in traffic)) or (
                fault=='invalid_receipt' and any(x.get('receipt_corrupted') for x in traffic))
            if not injected: issues.append('fault_not_injected')
            submits = [x for x in traffic if x['path'].endswith('/submit')]
            if len({x['request_body_sha256'] for x in submits}) != 1: issues.append('submit_changed')
            row = {**job,'case_id':case_id,'training_id':fixture['training_id'],
                'started_at':started_at,'ended_at':ended_at,'delivery_ms':delivery_ms,
                'wire_bytes':sum(x['request_bytes']+x.get('response_bytes',0) for x in traffic),
                'requests':len(traffic),'correct':not issues,'issues':issues,'fault_injected':injected,
                'exit_codes':codes,'pids':pids,'server_before':fault_before,'server_after':fault_after,
                'submit_attempts':len(submits),'remaining_queue':remaining}
            save(case_id+'-verification.json',{'actual':actual,'issues':issues,'traffic':traffic})
            append('cases.jsonl',row)
            print(f'CASE {index+1}/{len(jobs)} {case_id}: {"PASS" if not issues else issues} {delivery_ms:.1f}ms',flush=True)
    save('complete.json',{'at':time.time(),'cases':len(jobs)})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reps',type=int,default=8)
    p.add_argument('--smoke',action='store_true');p.add_argument('--limit',type=int)
    p.add_argument('--rep',type=int)
    asyncio.run(main(p.parse_args()))

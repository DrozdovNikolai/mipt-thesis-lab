"""Small host collector: raw samples first, YC Monitoring export in a separate thread."""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import urllib.request


def timestamp(t=None):
    return datetime.fromtimestamp(t or time.time(), UTC).isoformat().replace("+00:00", "Z")


def sample():
    cpu = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    memory = {s.split(':')[0]: int(s.split()[1]) * 1024 for s in Path('/proc/meminfo').read_text().splitlines()}
    disks = {}
    for path in Path('/sys/block').glob('vd*/stat'):
        numbers = list(map(int, path.read_text().split()))
        disks[path.parent.name] = {'read_bytes': numbers[2]*512, 'write_bytes': numbers[6]*512}
    return {'time': time.time(), 'cpu_ticks': cpu, 'cpu_count': os.cpu_count(), 'load1': os.getloadavg()[0], 'memory_total': memory['MemTotal'], 'memory_available': memory['MemAvailable'], 'disks': disks}


def containers():
    names = subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project'], text=True, timeout=10).split()
    if not names:
        return []
    info = json.loads(subprocess.check_output(['docker','inspect',*names], text=True, timeout=10))
    values = []
    for item in info:
        pid = item['State']['Pid']
        try:
            cg = next(line.split(':',2)[2] for line in Path(f'/proc/{pid}/cgroup').read_text().splitlines() if line.startswith('0:'))
            root = Path('/sys/fs/cgroup') / cg.lstrip('/')
            cpu = {s.split()[0]: int(s.split()[1]) for s in (root/'cpu.stat').read_text().splitlines()}
            values.append({'container': item['Config']['Labels']['com.docker.compose.service'], 'id': item['Id'], 'cpu_seconds': cpu['usage_usec']/1e6, 'memory_bytes': int((root/'memory.current').read_text()), 'throttled_seconds': cpu.get('throttled_usec',0)/1e6})
        except (FileNotFoundError, ProcessLookupError, StopIteration):
            continue
    return values


def exporter(folder, pending, output):
    token = ''
    expiry = 0
    while True:
        batch = pending.get()
        if batch is None:
            return
        try:
            if time.time() > expiry-120:
                request = urllib.request.Request('http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token', headers={'Metadata-Flavor':'Google'})
                with urllib.request.urlopen(request, timeout=5) as response:
                    credentials = json.load(response)
                token = credentials['access_token']
                expiry = time.time() + credentials['expires_in']
            request = urllib.request.Request('https://monitoring.api.cloud.yandex.net/monitoring/v2/data/write?folderId='+folder+'&service=custom', data=json.dumps(batch).encode(), headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=10) as response:
                result=json.load(response)
            if result.get('errorMessage'):
                raise RuntimeError('Monitoring rejected points: '+result['errorMessage'])
            row={'at':timestamp(),'points':len(batch['metrics']),'result':result}
        except Exception as error:
            row={'at':timestamp(),'error':type(error).__name__+': '+str(error),'points':len(batch['metrics'])}
        with (output/'metrics-export.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--role',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    pending=queue.Queue(maxsize=24)
    threading.Thread(target=exporter,args=(args.folder,pending,args.output),daemon=True).start()
    previous=sample()
    while True:
        time.sleep(10)
        current=sample()
        ticks=sum(current['cpu_ticks'])-sum(previous['cpu_ticks'])
        delta=[a-b for a,b in zip(current['cpu_ticks'],previous['cpu_ticks'])]
        context={}
        try: context=json.loads(Path('/opt/firefly-thesis/results/context.json').read_text())
        except (FileNotFoundError,json.JSONDecodeError): pass
        labels={'run_id':args.run_id,'role':args.role,'phase':str(context.get('phase','setup')),'profile':str(context.get('profile','none'))}
        raw={**current,'context':context,'containers':containers()}
        with (args.output/'host-samples.jsonl').open('a') as stream:
            stream.write(json.dumps(raw)+'\n')
        metrics=[]
        def point(name,value,extra=None):
            metrics.append({'name':'firefly_'+name,'labels':{**labels,**(extra or {})},'type':'DGAUGE','value':value})
        point('host_cpu_percent',100*(1-(delta[3]+delta[4])/max(1,ticks)))
        point('host_iowait_percent',100*delta[4]/max(1,ticks))
        point('host_steal_percent',100*delta[7]/max(1,ticks))
        point('host_memory_used_bytes',current['memory_total']-current['memory_available'])
        point('host_load1',current['load1'])
        for disk,values in current['disks'].items():
            for key,value in values.items():
                before=previous['disks'].get(disk,{}).get(key,value)
                point('host_disk_'+key+'_per_second',(value-before)/max(.01,current['time']-previous['time']),{'disk':disk})
        for c in raw['containers']:
            for key in ('cpu_seconds','memory_bytes','throttled_seconds'):
                point('container_'+key,c[key],{'container':c['container']})
        batch={'ts':timestamp(current['time']),'metrics':metrics}
        with (args.output/'metric-points.jsonl').open('a') as stream:
            stream.write(json.dumps(batch)+'\n')
        try: pending.put_nowait(batch)
        except queue.Full:
            with (args.output/'metrics-export.jsonl').open('a') as stream:
                stream.write(json.dumps({'at':timestamp(),'error':'export queue full; raw points retained'})+'\n')
        previous=current


if __name__=='__main__':
    main()

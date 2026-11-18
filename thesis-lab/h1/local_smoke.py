"""Run a frozen H1 package locally; never write inside the source bundle."""
import argparse
from datetime import datetime,UTC
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    bundle=a.bundle.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'raw').mkdir()
    subprocess.run(['sha256sum','--check','--quiet','SHA256SUMS'],cwd=bundle,check=True)
    project='firefly-thesis-h1-portable'
    for kind,flags in [('ps',['-aq']),('volume',['ls','-q']),('network',['ls','-q'])]:
        if subprocess.check_output(['docker',kind,*flags,'--filter','label=com.docker.compose.project='+project],text=True).strip():
            raise RuntimeError('Existing portable smoke project; will not reuse it')
    ids=subprocess.check_output(['docker','network','ls','-q'],text=True).split()
    nets=json.loads(subprocess.check_output(['docker','network','inspect',*ids],text=True))
    used=[ipaddress.ip_network(c['Subnet']) for n in nets for c in (n.get('IPAM',{}).get('Config') or []) if c.get('Subnet')]
    available=[ipaddress.ip_network(f'10.254.{i}.0/24') for i in range(220,240)]
    selected=[str(n) for n in available if not any(n.version==other.version and n.overlaps(other) for other in used)][:2]
    assert len(selected)==2
    compose=(bundle/'h1/compose.server.yml').read_text().replace('firefly-thesis-h1-v1',project)
    compose=compose.replace('../backend:',str(bundle/'backend')+':').replace('..:/lab:',str(bundle)+':/lab:').replace('../results:',str(out/'raw')+':').replace('../expanded/init.sql:',str(bundle/'expanded/init.sql')+':')
    compose=compose.replace("    ports: ['${SERVER_PRIVATE_IP:?set SERVER_PRIVATE_IP}:18000:8000']",'')
    compose=compose.replace('10.253.237.0/24',selected[0]).replace('10.253.238.0/24',selected[1])
    compose=compose.replace('volumes:\n  cloud_db:', '''  proxy:
    <<: *python
    command: python -m h1.proxy
    environment:
      <<: *env
      H1_BACKEND_URL: http://functional:8000
volumes:
  cloud_db:''')
    config=out/'compose.yml';config.write_text(compose)
    env={**os.environ,**{k:secrets.token_hex(24) for k in ('DB_PASSWORD','ADMIN_PASSWORD','JWT_SECRET_KEY','JWT_REFRESH_SECRET_KEY')},'SERVER_PRIVATE_IP':'127.0.0.1','THESIS_OUTPUT':'/results/portable'}
    base=['docker','compose','-f',str(config)]
    log=(out/'commands.log').open('w')
    def run(*args):
        log.write(' '.join(args)+'\n');log.flush()
        subprocess.run([*base,*args],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    result={'at':datetime.now(UTC).isoformat(),'paid_resources_created':False,'passed':False,
        'bundle_sha256sums':hashlib.sha256((bundle/'SHA256SUMS').read_bytes()).hexdigest()}
    try:
        run('up','-d','--wait','db','redis')
        run('run','--rm','runner','python','-m','expanded.init_db')
        run('up','-d','--wait','functional','proxy')
        run('run','--rm','-e','H1_BACKEND_URL=http://functional:8000','-e','H1_PROXY_URL=http://proxy:8001','runner','python','-m','h1.run_cases','--smoke','--reps','1')
        rows=[json.loads(l) for l in (out/'raw/portable/cases.jsonl').read_text().splitlines()]
        assert len(rows)==21 and all(r['correct'] for r in rows)
        result.update(passed=True,cases=len(rows))
    except BaseException as error:
        result['error']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        try:run('down','--volumes');result['local_resources_removed']=True
        except Exception:result['local_resources_removed']=False;result['passed']=False
        result['ended_at']=datetime.now(UTC).isoformat();(out/'result.json').write_text(json.dumps(result,indent=2));log.close();print(json.dumps(result,indent=2))
    subprocess.run(['sha256sum','--check','--quiet','SHA256SUMS'],cwd=bundle,check=True)

if __name__=='__main__':main()

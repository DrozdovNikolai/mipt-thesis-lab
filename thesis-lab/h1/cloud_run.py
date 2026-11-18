"""Orchestrate the declared two-host CPU replication and retain all partial runs."""

import argparse
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import tarfile
import time

from h1.ops import read, save, ssh_args, yc, refresh, stamp, check_owned
from h1.monitoring import Monitoring

ROOT=Path(__file__).resolve().parents[1]
REMOTE='/opt/firefly-thesis'
PROFILES=[{'id':'history-1k','n':1000,'pilots':1000},{'id':'history-10k','n':10000,'pilots':1000},{'id':'history-100k','n':100000,'pilots':1000},{'id':'pilots-100','n':100000,'pilots':100},{'id':'skew-80-10','n':100000,'pilots':1000,'skew':True},{'id':'neighbors-4','n':100000,'pilots':1000,'neighbors':4}]


class Run:
    def __init__(self,path):
        self.path=path.resolve()
        self.plan,self.state=read(self.path)
        self.log=(self.path/'orchestration.log').open('a')
        self.monitoring=Monitoring(self.path)

    def ssh(self,role,command,*,data=None,capture=False,timeout=1800,check=True):
        self.log.write(stamp()+' '+role+' '+command+'\n'); self.log.flush()
        result=subprocess.run(ssh_args(self.path,role)+[command],input=data,stdout=subprocess.PIPE if capture else self.log,stderr=self.log,timeout=timeout)
        if check: result.check_returncode()
        return result

    def send(self,role,relative,data,mode='0644'):
        path=REMOTE+'/'+relative
        command='install -d '+shlex.quote(str(Path(path).parent))+' && cat > '+shlex.quote(path)+' && chmod '+mode+' '+shlex.quote(path)
        self.ssh(role,'sudo sh -c '+shlex.quote(command),data=data)

    def remote(self,role,action,target,*args):
        command='cd '+REMOTE+' && sudo python3 -m h1.remote '+shlex.join([action,target,*map(str,args)])
        return self.ssh(role,command,timeout=18000 if action=='main' else 1800)

    def context(self,phase,profile):
        for role in ('server','loadgen'):
            self.remote(role,'context','telemetry',json.dumps({'phase':phase,'profile':profile}))

    def collect(self,role,target):
        destination=self.path/'artifacts'/role
        destination.mkdir(parents=True,exist_ok=True)
        archive=self.path/(role+'-checkpoint.tar')
        with archive.open('wb') as stream:
            result=subprocess.run(ssh_args(self.path,role)+['sudo tar -C '+REMOTE+'/results -cf - '+shlex.quote(target)],stdout=stream,stderr=self.log,timeout=300)
        result.check_returncode()
        with tarfile.open(archive) as tar:
            tar.extractall(destination,filter='data')
        archive.unlink()

    def dataset_to_loadgen(self,target):
        self.collect('server',target)
        data=(self.path/'artifacts/server'/target/'dataset.json').read_bytes()
        self.send('loadgen','results/'+target+'/dataset.json',data)

    def publish(self,target):
        directory=self.path/'artifacts/loadgen'/target
        for name in ('read-series.jsonl','mixed-series.jsonl'):
            file=directory/name
            if file.exists():
                points=self.monitoring.points(file,directory.name)
                for start in range(0,len(points),500):
                    self.monitoring.write(points[start:start+500])

    def readiness(self):
        for role in ('server','loadgen'):
            result=self.ssh(role,'sudo cloud-init status --wait && sudo systemctl is-active firefly-thesis-stop.timer && sudo systemctl show firefly-thesis-stop.timer --property=NextElapseUSecRealtime && sudo docker info --format \'{{.ServerVersion}}\' && sudo docker compose version',capture=True,timeout=600)
            (self.path/(role+'-readiness.txt')).write_bytes(result.stdout)

    def stop_test(self):
        instance=self.state['instances']['loadgen']
        before=stamp()
        self.ssh('loadgen','sudo systemctl start firefly-thesis-stop.service',check=False,timeout=30)
        transitions=[]
        until=time.monotonic()+180
        while time.monotonic()<until:
            actual=yc(self.plan,'compute','instance','get',instance['id'])
            check_owned(self.plan,self.state,actual)
            transitions.append({'at':stamp(),'status':actual['status']})
            if actual['status']=='STOPPED': break
            time.sleep(5)
        else: raise RuntimeError('Guest shutdown did not produce YC STOPPED')
        actual=yc(self.plan,'compute','instance','start',instance['id'])
        self.state=refresh(self.path)
        # sshd may not be ready when Compute reports RUNNING.
        for _ in range(30):
            check=self.ssh('loadgen','true',check=False,timeout=15)
            if check.returncode==0: break
            time.sleep(3)
        self.readiness()
        save(self.path/'auto-stop-test.json',{'started_at':before,'finished_at':stamp(),'passed':True,'transitions':transitions,'instance_id':instance['id'],'deadline_unchanged':self.state['deadline']})

    def setup(self,bundle):
        if (self.path/'uploaded.json').exists():
            raise RuntimeError('Already uploaded; do not replace source files during a run')
        self.readiness()
        self.stop_test()
        keydir=Path.home()/'.local/share/firefly-thesis'/self.state['run_id']
        keydir.mkdir(parents=True,exist_ok=True,mode=0o700)
        keydir.chmod(0o700)
        env={key:secrets.token_hex(24) for key in ('DB_PASSWORD','ADMIN_PASSWORD','JWT_SECRET_KEY','JWT_REFRESH_SECRET_KEY')}
        env['SERVER_PRIVATE_IP']='10.77.0.10'
        secret=keydir/'runtime.env'
        with secret.open('x') as stream:
            stream.write(''.join(key+'='+value+'\n' for key,value in env.items()))
        secret.chmod(0o600)
        subprocess.run(['sha256sum','--check','--quiet','SHA256SUMS'],cwd=bundle,check=True)
        filelist=[line.split('  ',1)[1] for line in (bundle/'SHA256SUMS').read_text().splitlines()]+['SHA256SUMS']
        for role in ('server','loadgen'):
            print('UPLOAD',role,stamp(),flush=True)
            source=subprocess.Popen(['tar','-C',str(bundle),'-cf','-',*filelist],stdout=subprocess.PIPE)
            destination=subprocess.run(ssh_args(self.path,role)+['tar -C '+REMOTE+' -xf -'],stdin=source.stdout,stdout=self.log,stderr=self.log,timeout=900)
            source.stdout.close()
            if source.wait(): raise RuntimeError('Source archive failed')
            destination.check_returncode()
            self.ssh(role,'cd '+REMOTE+' && sha256sum --check --quiet SHA256SUMS && sudo docker load -i images.tar.gz',timeout=900)
            self.send(role,'.runtime.env',secret.read_bytes(),mode='0600')
            self.send(role,'run-context.json',json.dumps({'run_id':self.state['run_id'],'role':role,'source_sha256sums':hashlib.sha256((bundle/'SHA256SUMS').read_bytes()).hexdigest()}).encode())
            probe="import json,subprocess; commands={'kernel':['uname','-a'],'cpu':['lscpu','--json'],'clock':['timedatectl','show'],'docker':['docker','version','--format','{{json .}}'],'packages':['dpkg-query','-W','docker.io','docker-compose-v2','python3']}; print(json.dumps({k:subprocess.check_output(v,text=True) for k,v in commands.items()},indent=2))"
            result=self.ssh(role,'sudo python3 -c '+shlex.quote(probe),capture=True)
            (self.path/(role+'-environment.json')).write_bytes(result.stdout)
            service='\n'.join(['[Unit]','Description=Firefly experiment metrics','After=network-online.target docker.service','[Service]','Type=simple','WorkingDirectory='+REMOTE,'ExecStart=/usr/bin/python3 -m h1.guest_metrics --folder '+self.plan['folder_id']+' --run-id '+self.state['run_id']+' --role '+role+' --output '+REMOTE+'/results/telemetry','Restart=on-failure','RestartSec=5','[Install]','WantedBy=multi-user.target',''])
            self.send(role,'metrics.service',service.encode())
            self.ssh(role,'sudo install -m 0644 '+REMOTE+'/metrics.service /etc/systemd/system/firefly-metrics.service && sudo systemctl daemon-reload && sudo systemctl enable --now firefly-metrics.service')
        save(self.path/'uploaded.json',{'at':stamp(),'bundle':str(bundle),'source_sha256sums':hashlib.sha256((bundle/'SHA256SUMS').read_bytes()).hexdigest()})

    def audit_sources(self, stage='before'):
        bundle=Path(json.loads((self.path/'uploaded.json').read_text())['bundle'])
        expected={line.split('  ',1)[1]:line.split('  ',1)[0] for line in (bundle/'SHA256SUMS').read_text().splitlines()}
        code="import sys,json,hashlib; from pathlib import Path; expected=json.load(sys.stdin); actual={name:hashlib.file_digest(Path(name).open('rb'),'sha256').hexdigest() for name in expected}; print(json.dumps({'files':actual,'mismatches':[name for name in expected if expected[name]!=actual[name]]}))"
        for role in ('server','loadgen'):
            result=self.ssh(role,'cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code),data=json.dumps(expected).encode(),capture=True)
            evidence=json.loads(result.stdout)
            save(self.path/(role+'-runtime-files-'+stage+'-main.json'),{'at':stamp(),**evidence})
            if evidence['mismatches']: raise RuntimeError('Source mismatch: '+role)

    def smoke(self):
        self.context('smoke','h1')
        self.remote('server','prepare','server')
        self.remote('loadgen','smoke','smoke')
        self.collect('loadgen','smoke')
        rows=[json.loads(line) for line in (self.path/'artifacts/loadgen/smoke/cases.jsonl').read_text().splitlines()]
        assert len(rows)==21 and all(r['correct'] for r in rows)
        save(self.path/'smoke-complete.json',{'at':stamp(),'cases':21,'passed':True})

    def main(self):
        if not (self.path/'smoke-complete.json').exists(): raise RuntimeError('Cloud smoke must pass first')
        if (self.path/'main-started.json').exists(): raise RuntimeError('Main series already started')
        self.audit_sources()
        plan=(ROOT/'h1/PLAN.md').read_bytes()
        (self.path/'H1_PLAN.md').write_bytes(plan)
        save(self.path/'main-started.json',{'at':stamp(),'plan_sha256':hashlib.sha256(plan).hexdigest(),'repeats':8,'expected_cases':768})
        for rep in range(8):
            self.context('main','block-'+str(rep))
            print('H1 BLOCK',rep,stamp(),flush=True)
            target='main/r'+str(rep)
            self.remote('loadgen','main',target,rep)
            self.collect('loadgen',target)
            points=self.monitoring.points(self.path/'artifacts/loadgen'/target/'cases.jsonl','main')
            for i in range(0,len(points),500): self.monitoring.write(points[i:i+500])
            save(self.path/'progress.json',{'at':stamp(),'completed_blocks':rep+1})
            # Billing is observational; an unavailable report must not discard a
            # completed measurement block or trigger a replay of its trials.
            try:
                from cloud.costs import snapshot
                snapshot(self.path)
            except Exception as error:
                save(self.path/f'cost-observation-error-r{rep}.json',
                     {'at':stamp(),'type':type(error).__name__,'message':str(error)})
        save(self.path/'main-complete.json',{'at':stamp()})

    def finish(self):
        self.audit_sources('after')
        self.context('backup','complete')
        self.remote('server','dump','backups')
        for role in ('server','loadgen'):
            self.ssh(role,'sudo systemctl stop firefly-metrics.service')
            code="from pathlib import Path; import hashlib; p=Path('results'); print(''.join(hashlib.file_digest(f.open('rb'),'sha256').hexdigest()+'  '+str(f.relative_to(p))+'\\n' for f in sorted(p.rglob('*')) if f.is_file()),end='')"
            result=self.ssh(role,'cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code),capture=True)
            (self.path/(role+'-REMOTE_SHA256SUMS')).write_bytes(result.stdout)
            self.collect(role,'.')
            directory=self.path/'artifacts'/role
            for line in result.stdout.decode().splitlines():
                digest,name=line.split('  ',1)
                if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=digest:
                    raise RuntimeError('Backup hash mismatch: '+role+'/'+name)
        restore=json.loads((self.path/'artifacts/server/backups/restore-check.json').read_text())
        assert restore['passed']
        counts=restore['counts']['functional']
        save(self.path/'aggregate-domain-counts.json', {'counts':counts,
            'two_grades_per_training':counts['final_report']==2*counts['training_session'],
            'seven_events_per_training':counts['training_session_crew_assignment_event']==7*counts['training_session'],
            'six_reports_per_training':counts['mistake_report']==6*counts['training_session'],
            'note':'Includes 21 cloud smoke cases and the main matrix; positive per-case parity plus aggregate counts checks for hidden duplicates.'})
        save(self.path/'backup-verified.json',{'at':stamp(),'passed':True,'run_id':self.state['run_id'],
            'main_completed':(self.path/'main-complete.json').exists(),
            'note':'Source/target file hashes; pg_dump TOC and full restore into empty DB with seven table counts'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['setup','smoke','main','finish','readiness']);p.add_argument('run',type=Path);p.add_argument('--bundle',type=Path);a=p.parse_args()
    run=Run(a.run)
    try:
        getattr(run,a.action)(a.bundle.resolve()) if a.action=='setup' else getattr(run,a.action)()
    except BaseException as error:
        save(run.path/(a.action+'-failure-'+datetime.now(UTC).strftime('%H%M%S')+'.json'),{'at':stamp(),'type':type(error).__name__,'message':str(error)})
        raise

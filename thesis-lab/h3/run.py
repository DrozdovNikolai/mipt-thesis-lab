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

from h3.ops import read, save, ssh_args, yc, refresh, stamp, check_owned
from h3.monitoring import Monitoring

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
        command='cd '+REMOTE+' && sudo python3 -m h3.remote '+shlex.join([action,target,*map(str,args)])
        return self.ssh(role,command,timeout=7200 if action=='mixed' else 1800)

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
            service='\n'.join(['[Unit]','Description=Firefly experiment metrics','After=network-online.target docker.service','[Service]','Type=simple','WorkingDirectory='+REMOTE,'ExecStart=/usr/bin/python3 -m cloud.guest_metrics --folder '+self.plan['folder_id']+' --run-id '+self.state['run_id']+' --role '+role+' --output '+REMOTE+'/results/telemetry','Restart=on-failure','RestartSec=5','[Install]','WantedBy=multi-user.target',''])
            self.send(role,'metrics.service',service.encode())
            self.ssh(role,'sudo install -m 0644 '+REMOTE+'/metrics.service /etc/systemd/system/firefly-metrics.service && sudo systemctl daemon-reload && sudo systemctl enable --now firefly-metrics.service')
        save(self.path/'uploaded.json',{'at':stamp(),'bundle':str(bundle),'source_sha256sums':hashlib.sha256((bundle/'SHA256SUMS').read_bytes()).hexdigest()})

    def profile(self,target,profile,repeats,requests,mixed=False,duration=30):
        if (self.path/'artifacts/loadgen'/target/'complete.json').exists():
            raise RuntimeError('Refusing to repeat a completed profile')
        print('PREPARE',target,stamp(),flush=True)
        self.context('prepare',profile['id'])
        self.remote('server','prepare',target,json.dumps(profile))
        if target=='smoke/reads':
            self.remote('server','validate',target)
        self.dataset_to_loadgen(target)
        self.remote('loadgen','check',target)
        if mixed:
            self.remote('server','worker',target)
            self.context('mixed',profile['id'])
            self.remote('loadgen','mixed',target,repeats,duration)
        else:
            for rep in range(repeats):
                if rep: self.remote('server','restart',target)
                self.context('reads',profile['id'])
                print('READ BLOCK',profile['id'],rep,stamp(),flush=True)
                self.remote('loadgen','reads',target,rep,requests)
        self.context('checkpoint',profile['id'])
        self.collect('server',target)
        self.collect('loadgen',target)
        self.publish(target)
        save(self.path/'artifacts/loadgen'/target/'complete.json',{'at':stamp(),'profile':profile,'repeats':repeats,'requests':requests,'mixed':mixed})
        print('COMPLETE',target,stamp(),flush=True)

    def smoke(self):
        self.profile('smoke/reads',{'id':'smoke-1k','n':1000,'pilots':100,'neighbors':1,'neighbor_n':20,'neighbor_pilots':5},1,4)
        self.profile('smoke/mixed',{'id':'smoke-mixed-1k','n':1000,'pilots':100},1,4,mixed=True,duration=2)
        save(self.path/'smoke-complete.json',{'at':stamp()})

    def main(self):
        if not (self.path/'smoke-complete.json').exists():
            raise RuntimeError('Cloud smoke must pass first')
        if (self.path/'main-started.json').exists():
            raise RuntimeError('Main series already started; preserve partial results')
        self.audit_sources()
        save(self.path/'main-started.json',{'at':stamp(),'profiles':PROFILES,'repeats':10,'requests':20,'mixed_repeats':10,'mixed_duration':30,'plan_sha256':hashlib.sha256((ROOT/'h3/PLAN.md').read_bytes()).hexdigest()})
        (self.path/'H3_PLAN.md').write_bytes((ROOT/'h3/PLAN.md').read_bytes())
        for profile in PROFILES:
            self.profile('reads/'+profile['id'],profile,10,20)
        self.profile('mixed/history-100k',PROFILES[2],10,20,mixed=True)
        self.context('coalescing','history-100k')
        self.remote('server','coalescing','mixed/history-100k')
        self.collect('server','mixed/history-100k')
        save(self.path/'main-complete.json',{'at':stamp()})

    def audit_sources(self):
        bundle=Path(json.loads((self.path/'uploaded.json').read_text())['bundle'])
        expected={line.split('  ',1)[1]:line.split('  ',1)[0] for line in (bundle/'SHA256SUMS').read_text().splitlines()}
        if (self.path/'runtime-overrides.json').exists():
            override=json.loads((self.path/'runtime-overrides.json').read_text())
            for name,value in override['files'].items():
                if expected.get(name)!=value['original_sha256']:
                    raise RuntimeError('Overlay does not match the original bundle: '+name)
                expected[name]=value['sha256']
        code="import sys,json,hashlib; from pathlib import Path; expected=json.load(sys.stdin); actual={name:hashlib.file_digest(Path(name).open('rb'),'sha256').hexdigest() for name in expected}; print(json.dumps({'files':actual,'mismatches':[name for name in expected if expected[name]!=actual[name]]}))"
        for role in ('server','loadgen'):
            result=self.ssh(role,'cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code),data=json.dumps(expected).encode(),capture=True)
            evidence=json.loads(result.stdout)
            save(self.path/(role+'-runtime-files-before-main.json'),{'at':stamp(),**evidence})
            if evidence['mismatches']: raise RuntimeError('Source mismatch before main: '+role)

    def finish(self):
        for role in ('server','loadgen'):
            prior=self.path/(role+'-runtime-files-before-main.json')
            expected=json.loads(prior.read_text())['files']
            code="import sys,json,hashlib; from pathlib import Path; expected=json.load(sys.stdin); actual={name:hashlib.file_digest(Path(name).open('rb'),'sha256').hexdigest() for name in expected}; print(json.dumps({'files':actual,'mismatches':[name for name in expected if expected[name]!=actual[name]]}))"
            result=self.ssh(role,'cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code),data=json.dumps(expected).encode(),capture=True)
            evidence=json.loads(result.stdout)
            save(self.path/(role+'-runtime-files-after-main.json'),{'at':stamp(),**evidence})
            if evidence['mismatches']:
                raise RuntimeError('Runtime source changed during measurements: '+role)
        self.context('backup','complete')
        # Quiesce the writer before database dumps and file manifests.
        code="from h3.remote import compose,environment; compose('server','stop','worker','worker-incremental',env=environment('backups'))"
        self.ssh('server','cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code))
        code="""import json,subprocess
from h3.remote import ROOT,environment,VARIANTS
env=environment('backups')
def fetch(query,database='incremental'):
    return json.loads(subprocess.check_output(['docker','compose','-f',str(ROOT/'h3/compose.server.yml'),'exec','-T','db','psql','-U','thesis','-d','thesis_exp_'+database,'-Atc',query],env=env,text=True))
query=\"SELECT coalesce(json_agg(x),'[]'::json) FROM (SELECT relname,pg_total_relation_size(relid) bytes,n_live_tup,n_dead_tup,n_tup_ins,n_tup_upd,n_tup_del FROM pg_stat_user_tables ORDER BY relname) x\"
values={v:fetch(query,v) for v in VARIANTS}
settings=fetch(\"SELECT json_object_agg(name,setting) FROM pg_settings WHERE name IN ('server_version','pg_stat_statements.track','pg_stat_statements.track_utility','pg_stat_statements.max','pg_stat_statements.save','track_io_timing','shared_buffers','max_parallel_workers_per_gather','max_connections','checkpoint_timeout','max_wal_size','wal_compression','synchronous_commit','fsync','full_page_writes','jit')\")
info=fetch('SELECT row_to_json(s) FROM pg_stat_statements_info s')
entries=fetch(\"SELECT json_build_object('entries',count(*),'non_toplevel_entries',count(*) FILTER (WHERE NOT toplevel)) FROM pg_stat_statements\")
facts=\"SELECT a.id assessment_id,a.user_id,t.id training_id,coalesce(t.completed_at,t.updated_at,t.created_at) effective_at,a.created_at assessment_created_at FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id WHERE a.user_id IS NOT NULL AND t.status='COMPLETED'\"
grades=\"SELECT DISTINCT ON(r.assessment_id,r.competence_id) r.assessment_id,r.competence_id,coalesce(r.grade_code_snapshot,r.grade) grade_code,r.grade_label_snapshot grade_label,r.grade_score_snapshot grade_score_numeric,r.grade_color_hex_snapshot grade_color_hex FROM final_report r JOIN crew_member_assessment a ON a.id=r.assessment_id JOIN training_session t ON t.id=a.training_session_id WHERE a.user_id IS NOT NULL AND t.status='COMPLETED' ORDER BY r.assessment_id,r.competence_id,r.updated_at DESC,r.created_at DESC,r.id DESC\"
latest='SELECT DISTINCT ON(user_id) user_id,assessment_id FROM ('+facts+') f ORDER BY user_id,effective_at DESC,assessment_created_at DESC,assessment_id DESC'
parity={}
for variant in ('projection','incremental'):
    parity[variant]={}
    for table,expected in (('commander_assessment_fact',facts),('commander_grade_fact',grades),('commander_latest_assessment',latest)):
        query=\"WITH expected AS MATERIALIZED (\"+expected+\"), missing AS (SELECT * FROM expected EXCEPT ALL SELECT * FROM \"+table+\"), extra AS (SELECT * FROM \"+table+\" EXCEPT ALL SELECT * FROM expected) SELECT json_build_object('expected_rows',(SELECT count(*) FROM expected),'actual_rows',(SELECT count(*) FROM \"+table+\"),'missing_rows',(SELECT count(*) FROM missing),'extra_rows',(SELECT count(*) FROM extra))\"
        parity[variant][table]=fetch(query,variant)
    queue_query=\"SELECT json_build_object('pending',(SELECT count(*) FROM commander_dirty_pilot))\" if variant=='projection' else \"SELECT json_build_object('pending',(SELECT count(*) FROM commander_dirty_assessment)+(SELECT count(*) FROM commander_dirty_training))\"
    parity[variant]['queue']=fetch(queue_query,variant)
parity['passed']=all(parity[v]['queue']['pending']==0 and all(parity[v][t]['missing_rows']==parity[v][t]['extra_rows']==0 for t in ('commander_assessment_fact','commander_grade_fact','commander_latest_assessment')) for v in ('projection','incremental'))
print(json.dumps({'tables':values,'settings':settings,'pg_stat_statements_info':info,'statement_entries':entries,'post_workload_parity':parity}))
"""
        result=self.ssh('server','cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code),capture=True)
        save(self.path/'storage-after-workload.json',{'at':stamp(),**json.loads(result.stdout),
            'note':'After all mixed, crash and coalescing cases; physical relation sizes, approximate pg_stat tuple counters, settings and statement-tracker metadata. Not part of latency/WAL measurement windows.'})
        self.remote('server','dump','backups')
        for role in ('server','loadgen'):
            self.ssh(role,'sudo systemctl stop firefly-metrics.service')
            # Manifest is calculated after collector shutdown and before transfer.
            code="from pathlib import Path; import hashlib; p=Path('results'); print(''.join(hashlib.file_digest(f.open('rb'),'sha256').hexdigest()+'  '+str(f.relative_to(p))+'\\n' for f in sorted(p.rglob('*')) if f.is_file() and f.name!='REMOTE_SHA256SUMS'),end='')"
            result=self.ssh(role,'cd '+REMOTE+' && sudo python3 -c '+shlex.quote(code),capture=True)
            (self.path/(role+'-REMOTE_SHA256SUMS')).write_bytes(result.stdout)
            self.collect(role,'.')
            directory=self.path/'artifacts'/role
            for line in result.stdout.decode().splitlines():
                digest,name=line.split('  ',1)
                with (directory/name).open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:
                        raise RuntimeError('Backup hash mismatch: '+role+'/'+name)
        save(self.path/'backup-verified.json',{'at':stamp(),'passed':True,'run_id':self.state['run_id'],'main_completed':(self.path/'main-complete.json').exists(),'note':'File hashes and five pg_dump TOCs checked; candidate fully restored into an empty DB, eight key table counts compared'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('setup','smoke','main','finish','readiness'))
    parser.add_argument('run',type=Path)
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    run=Run(args.run)
    try:
        getattr(run,args.action)(args.bundle.resolve()) if args.action=='setup' else getattr(run,args.action)()
    except BaseException as error:
        save(run.path/(args.action+'-failure-'+datetime.now(UTC).strftime('%H%M%S')+'.json'),{'at':stamp(),'type':type(error).__name__,'message':str(error)})
        raise

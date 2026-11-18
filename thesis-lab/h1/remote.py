"""Commands restricted to the new H1 experiment Compose projects."""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess

ROOT=Path('/opt/firefly-thesis')

def environment(target):
    if not (ROOT/'run-context.json').exists(): raise RuntimeError('Missing experiment marker')
    if Path(target).is_absolute() or '..' in Path(target).parts: raise ValueError(target)
    secrets={line.split('=',1)[0]:line.split('=',1)[1] for line in (ROOT/'.runtime.env').read_text().splitlines() if line and not line.startswith('#')}
    return {**os.environ,**secrets,'THESIS_OUTPUT':'/results/'+target}

def compose(role,*args,env):
    return subprocess.run(['docker','compose','-f',str(ROOT/f'h1/compose.{role}.yml'),*map(str,args)],env=env,cwd=ROOT,check=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['context','prepare','smoke','main','dump']);p.add_argument('target');p.add_argument('args',nargs='*');a=p.parse_args()
    env=environment(a.target);out=ROOT/'results'/a.target;out.mkdir(parents=True,exist_ok=True)
    if a.action=='context':
        body=json.loads(a.args[0]);body['at']=datetime.now(UTC).isoformat()
        temporary=ROOT/'results/context.tmp';temporary.write_text(json.dumps(body));temporary.replace(ROOT/'results/context.json')
    elif a.action=='prepare':
        if (ROOT/'results/schema-created.json').exists(): raise RuntimeError('Refusing to reset experiment DB')
        compose('server','up','-d','--wait','db','redis',env=env)
        compose('server','run','--rm','runner','python','-m','expanded.init_db',env=env)
        compose('server','up','-d','--wait','functional',env=env)
        (ROOT/'results/schema-created.json').write_text(json.dumps({'at':datetime.now(UTC).isoformat()}))
    elif a.action in ('smoke','main'):
        proxy_env=environment('proxy')
        compose('loadgen','up','-d','proxy',env=proxy_env)
        flags=['--smoke','--reps','1'] if a.action=='smoke' else ['--rep',a.args[0]]
        compose('loadgen','run','--rm','--no-deps','runner','python','-m','h1.run_cases',*flags,env=env)
    elif a.action=='dump':
        compose('server','stop','functional',env=env)
        base=['docker','compose','-f',str(ROOT/'h1/compose.server.yml'),'exec','-T','db']
        with (out/'functional.dump').open('xb') as f:
            subprocess.run([*base,'pg_dump','-U','thesis','-Fc','thesis_exp_functional'],stdout=f,env=env,check=True)
        with (out/'functional.dump').open('rb') as f,(out/'functional-toc.txt').open('w') as result:
            subprocess.run([*base,'pg_restore','--list'],stdin=f,stdout=result,env=env,check=True)
        subprocess.run([*base,'psql','-U','thesis','-d','postgres','-v','ON_ERROR_STOP=1','-c','CREATE DATABASE thesis_exp_restore'],env=env,check=True)
        with (out/'functional.dump').open('rb') as f:
            subprocess.run([*base,'pg_restore','-U','thesis','-d','thesis_exp_restore','--exit-on-error'],stdin=f,env=env,check=True)
        tables=['training_session','crew_member_assessment','training_session_crew_state','training_session_crew_assignment_event','training_session_exercise_run','final_report','mistake_report']
        query='SELECT json_build_object('+','.join("'"+t+"',(SELECT count(*) FROM "+t+")" for t in tables)+')'
        counts={name:json.loads(subprocess.check_output([*base,'psql','-U','thesis','-d','thesis_exp_'+name,'-Atc',query],env=env,text=True)) for name in ('functional','restore')}
        assert counts['functional']==counts['restore']
        (out/'restore-check.json').write_text(json.dumps({'passed':True,'counts':counts},indent=2))

if __name__=='__main__': main()

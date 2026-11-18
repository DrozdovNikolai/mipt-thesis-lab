"""Commands executed inside the temporary VM; all SQL targets the experiment DBs."""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path('/opt/firefly-thesis')
VARIANTS=('original','optimized','projection')


def environment(target):
    if not (ROOT/'run-context.json').exists():
        raise RuntimeError('Experiment identity marker is missing')
    path=Path(target)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Output path must be relative to experiment results')
    secret={}
    for line in (ROOT/'.runtime.env').read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            key,value=line.split('=',1)
            secret[key]=value
    return {**os.environ,**secret,'THESIS_OUTPUT':'/results/'+target}


def compose(role,*args,env):
    return subprocess.run(['docker','compose','-f',str(ROOT/f'cloud/compose.{role}.yml'),*map(str,args)],env=env,cwd=ROOT,check=True)


def inside(env,module,*args,database='seed'):
    assert database in ('seed',*VARIANTS)
    url='postgresql+asyncpg://thesis:'+env['DB_PASSWORD']+'@db:5432/thesis_exp_'+database
    compose('server','run','--rm','--no-deps','-e','DATABASE_URL','-e','DATABASE_SYNC_URL','runner','python','-m','cloud.entry',module,*args,env={**env,'DATABASE_URL':url,'DATABASE_SYNC_URL':url.replace('postgresql+asyncpg','postgresql+psycopg')})


def prepare(env,profile):
    compose('server','up','-d','--wait','db','redis',env=env)
    compose('server','stop',*VARIANTS,'seed','worker',env=env)
    inside(env,'expanded.init_db')
    compose('server','up','-d','--wait','seed',env=env)
    inside(env,'expanded.dataset',json.dumps(profile))
    compose('server','stop','seed',env=env)
    for variant in VARIANTS:
        for sql in (f'DROP DATABASE IF EXISTS thesis_exp_{variant} WITH (FORCE)',f'CREATE DATABASE thesis_exp_{variant} TEMPLATE thesis_exp_seed'):
            compose('server','exec','-T','db','psql','-U','thesis','-d','postgres','-v','ON_ERROR_STOP=1','-c',sql,env=env)
        inside(env,'expanded.install',variant,database=variant)
    compose('server','up','-d','--wait',*VARIANTS,env=env)
    for variant in VARIANTS:
        inside(env,'expanded.explain',variant,database=variant)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','check','reads','mixed','restart','worker','context','dump'))
    parser.add_argument('target')
    parser.add_argument('args',nargs='*')
    a=parser.parse_args()
    env=environment(a.target)
    output=ROOT/'results'/a.target
    output.mkdir(parents=True,exist_ok=True)
    if a.action=='context':
        data=json.loads(a.args[0])
        data['at']=datetime.now(UTC).isoformat()
        tmp=ROOT/'results/context.tmp'
        tmp.write_text(json.dumps(data))
        tmp.replace(ROOT/'results/context.json')
    elif a.action=='prepare':
        if (output/'dataset.json').exists():
            raise RuntimeError('Refusing to overwrite an existing dataset')
        prepare(env,json.loads(a.args[0]))
    elif a.action=='restart':
        compose('server','restart','-t','2',*VARIANTS,env=env)
        compose('server','up','-d','--wait',*VARIANTS,env=env)
    elif a.action=='worker':
        compose('server','up','-d','--force-recreate','worker',env=env)
    elif a.action in ('check','reads','mixed'):
        if a.action=='check': args=('expanded.reads','--check')
        elif a.action=='reads': args=('expanded.reads','--rep',a.args[0],'--requests',a.args[1])
        else: args=('expanded.mixed','--repeats',a.args[0],'--duration',a.args[1])
        time.sleep(2)
        compose('loadgen','run','--rm','--no-deps','runner','python','-m','cloud.entry',*args,env=env)
    elif a.action=='dump':
        for name in ('seed',*VARIANTS):
            with (output/(name+'.dump')).open('xb') as stream:
                subprocess.run(['docker','compose','-f',str(ROOT/'cloud/compose.server.yml'),'exec','-T','db','pg_dump','-U','thesis','-Fc','thesis_exp_'+name],stdout=stream,env=env,check=True)
            with (output/(name+'.dump')).open('rb') as source, (output/(name+'-toc.txt')).open('w') as result:
                subprocess.run(['docker','compose','-f',str(ROOT/'cloud/compose.server.yml'),'exec','-T','db','pg_restore','--list'],stdin=source,stdout=result,env=env,check=True)


if __name__=='__main__':
    main()

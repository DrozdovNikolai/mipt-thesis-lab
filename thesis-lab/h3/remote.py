"""Commands executed inside the temporary VM; all SQL targets the experiment DBs."""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path('/opt/firefly-thesis')
VARIANTS=('original','optimized','projection','incremental')


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
    return subprocess.run(['docker','compose','-f',str(ROOT/f'h3/compose.{role}.yml'),*map(str,args)],env=env,cwd=ROOT,check=True)


def inside(env,module,*args,database='seed'):
    assert database in ('seed','validation',*VARIANTS)
    url='postgresql+asyncpg://thesis:'+env['DB_PASSWORD']+'@db:5432/thesis_exp_'+database
    compose('server','run','--rm','--no-deps','-e','DATABASE_URL','-e','DATABASE_SYNC_URL','runner','python','-m','h3.entry',module,*args,env={**env,'DATABASE_URL':url,'DATABASE_SYNC_URL':url.replace('postgresql+asyncpg','postgresql+psycopg')})


def prepare(env,profile):
    compose('server','up','-d','--wait','db','redis',env=env)
    compose('server','stop',*VARIANTS,'seed','worker','worker-incremental',env=env)
    inside(env,'expanded.init_db')
    compose('server','up','-d','--wait','seed',env=env)
    inside(env,'h3.dataset',json.dumps(profile))
    compose('server','stop','seed',env=env)
    for variant in VARIANTS:
        for sql in (f'DROP DATABASE IF EXISTS thesis_exp_{variant} WITH (FORCE)',f'CREATE DATABASE thesis_exp_{variant} TEMPLATE thesis_exp_seed'):
            compose('server','exec','-T','db','psql','-U','thesis','-d','postgres','-v','ON_ERROR_STOP=1','-c',sql,env=env)
        inside(env,'h3.install',variant,database=variant)
    compose('server','up','-d','--wait',*VARIANTS,env=env)
    for variant in VARIANTS:
        inside(env,'h3.explain',variant,database=variant)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','check','reads','mixed','restart','worker','context','dump','validate','coalescing'))
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
        compose('server','up','-d','--force-recreate','worker','worker-incremental',env=env)
    elif a.action=='validate':
        for query in ('DROP DATABASE IF EXISTS thesis_exp_validation WITH (FORCE)', 'CREATE DATABASE thesis_exp_validation TEMPLATE thesis_exp_seed'):
            compose('server','exec','-T','db','psql','-U','thesis','-d','postgres','-v','ON_ERROR_STOP=1','-c',query,env=env)
        inside(env,'h3.validate',database='validation')
    elif a.action=='coalescing':
        compose('server','stop','worker','worker-incremental',env=env)
        for variant in ('projection','incremental'):
            inside(env,'h3.coalescing',variant,database=variant)
    elif a.action in ('check','reads','mixed'):
        if a.action=='check': args=('h3.reads','--check')
        elif a.action=='reads': args=('h3.reads','--rep',a.args[0],'--requests',a.args[1])
        else: args=('h3.mixed','--repeats',a.args[0],'--duration',a.args[1])
        time.sleep(2)
        compose('loadgen','run','--rm','--no-deps','runner','python','-m','h3.entry',*args,env=env)
    elif a.action=='dump':
        for name in ('seed',*VARIANTS):
            with (output/(name+'.dump')).open('xb') as stream:
                subprocess.run(['docker','compose','-f',str(ROOT/'h3/compose.server.yml'),'exec','-T','db','pg_dump','-U','thesis','-Fc','thesis_exp_'+name],stdout=stream,env=env,check=True)
            with (output/(name+'.dump')).open('rb') as source, (output/(name+'-toc.txt')).open('w') as result:
                subprocess.run(['docker','compose','-f',str(ROOT/'h3/compose.server.yml'),'exec','-T','db','pg_restore','--list'],stdin=source,stdout=result,env=env,check=True)
        base=['docker','compose','-f',str(ROOT/'h3/compose.server.yml'),'exec','-T','db']
        subprocess.run([*base,'psql','-U','thesis','-d','postgres','-v','ON_ERROR_STOP=1','-c',
            'CREATE DATABASE thesis_exp_restore'],env=env,check=True)
        with (output/'incremental.dump').open('rb') as source:
            subprocess.run([*base,'pg_restore','-U','thesis','-d','thesis_exp_restore','--exit-on-error'],
                stdin=source,env=env,check=True)
        tables=['training_session','crew_member_assessment','final_report','commander_assessment_fact',
                'commander_grade_fact','commander_latest_assessment','commander_dirty_assessment','commander_dirty_training']
        statement='SELECT json_build_object('+','.join("'"+t+"',(SELECT count(*) FROM "+t+")" for t in tables)+')'
        counts={db:json.loads(subprocess.check_output([*base,'psql','-U','thesis','-d','thesis_exp_'+db,'-Atc',statement],env=env,text=True)) for db in ('incremental','restore')}
        assert counts['incremental']==counts['restore']
        (output/'restore-check.json').write_text(json.dumps({'passed':True,'restored_database':'incremental',
            'method':'pg_restore --exit-on-error into empty DB; source and restored counts of eight key tables',
            'counts':counts,'at':datetime.now(UTC).isoformat()},indent=2)+'\n')


if __name__=='__main__':
    main()

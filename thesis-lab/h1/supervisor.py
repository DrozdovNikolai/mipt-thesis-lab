"""A real backend process, restarted after an injected crash; no Docker socket."""
import os
import subprocess
import sys
import time
import json
import psycopg
from h1.common import append, OUT

while True:
    child = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'h1.server:app',
                              '--host', '0.0.0.0', '--port', '8000', '--no-access-log'])
    append('backend-processes.jsonl', {'event':'start', 'pid':child.pid})
    code = child.wait()
    append('backend-processes.jsonl', {'event':'exit', 'pid':child.pid, 'code':code})
    if code != 77:
        sys.exit(code)
    fault = json.loads((OUT/'faults.jsonl').read_text().splitlines()[-1])
    tid = fault['training_id']
    url = os.environ['DATABASE_SYNC_URL'].replace('postgresql+psycopg://','postgresql://')
    with psycopg.connect(url) as connection:
        row = connection.execute('''SELECT t.status,t.submitted_at,s.sealed_at,
            (SELECT count(*) FROM final_report r JOIN crew_member_assessment a
             ON a.id=r.assessment_id WHERE a.training_session_id=t.id)
            FROM training_session t JOIN training_session_crew_state s ON s.training_session_id=t.id
            WHERE t.id=%s''',(tid,)).fetchone()
    passed = row[0]=='IN_PROGRESS' and row[1] is None and row[2] is None and row[3]==0
    append('crash-rollback-checks.jsonl',{'training_id':tid,'passed':passed,
        'status':row[0],'submitted':row[1] is not None,'sealed':row[2] is not None,'grades':row[3]})
    if not passed:
        raise RuntimeError('Uncommitted submit left a partial result after process exit')
    time.sleep(0.5)

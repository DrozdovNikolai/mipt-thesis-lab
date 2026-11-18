"""Read local progress records without probing or disturbing the cloud workload."""
import ast
import json
from pathlib import Path
import re
import sys


def status(run):
    load=lambda name:json.loads((run/name).read_text()) if (run/name).exists() else {}
    lines=(run/'orchestration.log').read_text().splitlines()
    starts=[i for i,line in enumerate(lines) if 'h3.remote mixed mixed/history-100k ' in line]
    cases=[]
    if starts:
        for line in lines[starts[-1]+1:]:
            match=re.fullmatch(r'MIXED (\{.*\}) writes (\d+) seconds ([\d.]+)',line)
            if match:
                cases.append({**ast.literal_eval(match[1]),'writes':int(match[2]),'elapsed_s':float(match[3])})
    return {
        'completed_read_profiles':len(list((run/'artifacts/loadgen/reads').glob('*/complete.json'))),
        'mixed_started':bool(starts),'mixed_cases_completed':len(cases),
        'latest_mixed_case':cases[-1] if cases else None,
        'main_completed':bool(load('main-complete.json')),
        'backup_verified':load('backup-verified.json').get('passed',False),
        'cleanup_complete':load('cleanup.json').get('complete',False),
        'deadline':load('resources.json').get('deadline'),
    }


if __name__=='__main__':
    print(json.dumps(status(Path(sys.argv[1])),indent=2))

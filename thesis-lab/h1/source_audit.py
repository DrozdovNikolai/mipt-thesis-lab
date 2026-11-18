"""Read-only snapshot of tracked source bytes in the four primary checkouts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import UTC,datetime

ROOT=Path(__file__).resolve().parents[2]

def snapshot():
    result={'at':datetime.now(UTC).isoformat(),'repositories':{}}
    for name in ('firefly-backend','firefly-instructor','firefly-commander','firefly-session'):
        root=ROOT/name
        files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
        result['repositories'][name]={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'status_sha256':hashlib.sha256(subprocess.check_output(['git','status','--porcelain=v1','-z'],cwd=root)).hexdigest(),
            'files':{f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files if f and (root/f).is_file()}}
    return result

if __name__=='__main__':
    path=Path(sys.argv[1]);value=snapshot()
    if len(sys.argv)>2:
        before=json.loads(Path(sys.argv[2]).read_text())
        value['comparison']={name:{'head_equal':r['head']==before['repositories'][name]['head'],
            'files_equal':r['files']==before['repositories'][name]['files'],
            'status_equal':r['status_sha256']==before['repositories'][name]['status_sha256']}
            for name,r in value['repositories'].items()}
    with path.open('x') as f: json.dump(value,f,indent=2)
    print('Snapshot saved:',path)

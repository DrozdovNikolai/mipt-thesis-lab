"""Seal a finished, backed-up, cleaned cloud run without modifying its raw data."""

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

from cloud.ops import save


def seal(run):
    for name, field in (('main-complete.json',None),('backup-verified.json','passed'),('cleanup.json','complete')):
        record=json.loads((run/name).read_text())
        if field and not record.get(field):
            raise RuntimeError(name+' is not complete')
    if (run/'SHA256SUMS').exists():
        raise RuntimeError('Preserve the existing seal; create an explicitly versioned new manifest if necessary')
    snapshot=run/'controller-final'
    snapshot.mkdir(exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    for name in ("cloud", "h3", "h1"):
        (snapshot/name).mkdir()
        for file in (root/name).iterdir():
            if file.is_file():
                shutil.copy2(file,snapshot/name/file.name)
    paths=sorted(f for f in run.rglob('*') if f.is_file() and f.name not in ('SHA256SUMS','seal.json'))
    # This private file remains outside the result archive. Never print its values.
    secret=Path.home()/'.local/share/firefly-thesis'/run.name/'runtime.env'
    values=[line.split('=',1)[1].encode() for line in secret.read_text().splitlines()
            if line and line.split('=',1)[0] in ('DB_PASSWORD','ADMIN_PASSWORD','JWT_SECRET_KEY','JWT_REFRESH_SECRET_KEY')]
    hits=[]
    lines=[]
    for file in paths:
        digest=hashlib.sha256()
        tail=b''
        with file.open('rb') as stream:
            while chunk:=stream.read(1024*1024):
                digest.update(chunk)
                scan=tail+chunk
                if any(value in scan for value in values):
                    hits.append(str(file.relative_to(run)))
                tail=scan[-128:]
        lines.append(digest.hexdigest()+'  '+str(file.relative_to(run))+'\n')
    if hits:
        raise RuntimeError('Runtime secret found in output files: '+', '.join(sorted(set(hits))))
    manifest=''.join(lines).encode()
    (run/'SHA256SUMS').write_bytes(manifest)
    evidence={'sealed_at':datetime.now(UTC).isoformat(),'files':len(paths),
              'sha256sums_sha256':hashlib.sha256(manifest).hexdigest(),
              'runtime_plaintext_secret_scan_passed':True,
              'excludes':['SHA256SUMS','seal.json'],
              'note':'File manifest covers the archived controller, measurements, database dumps, cloud records and analysis; the manifest hash is in this record.'}
    save(run/'seal.json',evidence)
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    seal(Path(sys.argv[1]).resolve())

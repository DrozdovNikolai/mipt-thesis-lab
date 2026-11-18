"""Explicit online acquisition; inference runs locally with networking disabled."""
import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download

REPO = 'nvidia/parakeet-tdt-0.6b-v2'
REVISION = 'ae9ad07059c7c739ffaf932226a8fe64ae2620b0'
root = Path('/experiment')
output = Path('/output')
root.mkdir(exist_ok=True)
os.chown(root, 10001, 10001)
directory = root/'parakeet'
snapshot_download(REPO, revision=REVISION, local_dir=directory,
                  allow_patterns=['*.nemo', 'README.md'])
files = {}
for path in directory.iterdir():
    if path.is_file():
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8*1024*1024), b''):
                digest.update(chunk)
        files[path.name] = {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}
manifest = {'repo': REPO, 'revision': REVISION, 'files': files,
            'source': 'https://huggingface.co/'+REPO, 'audio_uploaded': False}
output.mkdir(exist_ok=True)
destination = output/'model-manifest.json'
if destination.exists():
    assert json.loads(destination.read_bytes()) == manifest
else:
    destination.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
print(json.dumps(manifest), flush=True)

"""Explicit acquisition of the reviewed pinned FP16 large-v3 CT2 conversion."""

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from north55_speech.core import atomic_json, file_hash, now

REPO = 'Systran/faster-whisper-large-v3'
REVISION = 'edaa852ec7e145841d8ffdb056a99866b5f0a478'
NAME = 'whisper-large-v3-systran-ct2'
FILES = ('README.md', 'config.json', 'model.bin', 'preprocessor_config.json', 'tokenizer.json', 'vocabulary.json')


def main():
    report = Path('/reports/language-large-v1')
    metadata = json.loads((report / 'model-source.json').read_bytes())
    if metadata['sha'] != REVISION or metadata['cardData']['license'] != 'mit':
        raise ValueError('Reviewed model revision or license differs')
    entries = {r['rfilename']: r for r in metadata['siblings']}
    root = Path('/models') / NAME
    root.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name in FILES:
        entry, target = entries[name], root / name
        url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}'
        started = time.perf_counter()
        downloaded = not target.exists()
        if downloaded:
            partial = target.with_suffix(target.suffix + '.part')
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            if offset < entry['size']:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                    if offset and (response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-')):
                        raise ValueError('Server did not honor resume range; partial preserved')
                    with partial.open('ab' if offset else 'xb') as output:
                        count = offset
                        while chunk := response.read(4 * 1024 * 1024):
                            count += len(chunk)
                            if count > entry['size']:
                                raise ValueError('Download exceeds pinned size')
                            output.write(chunk)
            validate_file(partial, entry)
            partial.replace(target)
        validate_file(target, entry)
        evidence.append({'name': name, 'url': url, 'bytes': target.stat().st_size,
            'sha256': file_hash(target), 'publisher_lfs_sha256': entry.get('lfs', {}).get('sha256'),
            'publisher_git_blob_sha1': entry['blobId'], 'downloaded_now': downloaded,
            'elapsed_sec': time.perf_counter() - started})
        print(json.dumps(evidence[-1]), flush=True)
    manifest = {'model': NAME, 'repo': REPO, 'revision': REVISION, 'license': 'MIT',
        'upstream': 'openai/whisper-large-v3', 'format': 'CTranslate2 FP16 conversion by SYSTRAN',
        'files': {r['name']: r['sha256'] for r in evidence}, 'acquired_at': now().isoformat(),
        'source_metadata_sha256': file_hash(report / 'model-source.json')}
    existing = root / 'manifest.json'
    if existing.exists():
        old = json.loads(existing.read_bytes())
        if any(old[k] != manifest[k] for k in ('model', 'repo', 'revision', 'license', 'files', 'source_metadata_sha256')):
            raise ValueError('Existing model manifest differs; preserve it')
        manifest = old
    else:
        atomic_json(existing, manifest)
    atomic_json(report / 'model-acquisition.json', {'status': 'ACQUIRED_CHECKSUM_VERIFIED',
        'manifest': manifest, 'manifest_sha256': file_hash(existing), 'files': evidence,
        'script_sha256': file_hash(Path(__file__))})


def validate_file(path, entry):
    if path.stat().st_size != entry['size']:
        raise ValueError('Incomplete model file')
    if 'lfs' in entry:
        valid = file_hash(path) == entry['lfs']['sha256']
    else:
        content = path.read_bytes()
        valid = hashlib.sha1(f'blob {len(content)}\0'.encode() + content, usedforsecurity=False).hexdigest() == entry['blobId']
    if not valid:
        raise ValueError('Pinned publisher checksum mismatch; file preserved')


if __name__ == '__main__':
    main()

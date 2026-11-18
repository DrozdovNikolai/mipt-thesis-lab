"""Explicit checksum-pinned EN/RU training acquisition; no test audio."""
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path('data/input/pair-quality-sources-v1')
SOURCES = {
    'librispeech': {'repo': 'openslr/librispeech_asr', 'revision': '71cacbfb7e2354c4226d01e70d77d5fca3d04ba1',
                   'files': ['clean/train.100/0000.parquet']},
    'fleurs': {'repo': 'google/fleurs', 'revision': '70bb2e84b976b7e960aa89f1c648e09c59f894dd',
               'files': ['data/ru_ru/train.tsv', 'data/ru_ru/audio/train.tar.gz']},
}


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def acquire():
    plan = {'sources': SOURCES, 'scope': 'general_speech_training_only', 'limit_per_language': 200,
            'selection': 'publisher order, 1-30 sec, nonempty text; no ASR-based selection',
            'manual_audio_verification': False, 'test_downloaded': False, 'files': []}
    for name, source in SOURCES.items():
        metadata = json.loads((ROOT / f'{name}-api.json').read_bytes())
        if metadata['sha'] != source['revision'] or metadata['cardData']['license'] != ['cc-by-4.0']:
            raise ValueError('Publisher revision or license differs')
        by_name = {f['rfilename']: f for f in metadata['siblings']}
        for filename in source['files']:
            meta = by_name[filename]
            plan['files'].append({'source': name, 'filename': filename, 'size': meta['size'],
                'checksum': meta['lfs']['sha256'] if 'lfs' in meta else meta['blobId'],
                'algorithm': 'sha256' if 'lfs' in meta else 'git_blob_sha1',
                'local': f'{name}-{Path(filename).name}',
                'url': f'https://huggingface.co/datasets/{source["repo"]}/resolve/{source["revision"]}/{filename}'})
    plan_path = ROOT / 'training-support-plan.json'
    if plan_path.exists() and json.loads(plan_path.read_bytes()) != plan:
        raise ValueError('Acquisition plan changed')
    plan_path.write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    evidence = []
    for name, source in SOURCES.items():
        card = ROOT / f'{name}-README.md'
        if not card.exists():
            url = f'https://huggingface.co/datasets/{source["repo"]}/resolve/{source["revision"]}/README.md'
            with urllib.request.urlopen(url, timeout=45) as r:
                card.write_bytes(r.read(2_000_000))
    card = (ROOT / 'fleurs-README.md').read_text(encoding='utf-8')
    if 'Speakers of the train sets are different than speakers from the dev/test sets.' not in card:
        raise ValueError('Publisher speaker-disjointness statement missing')
    for entry in plan['files']:
        path = ROOT / entry['local']
        if not path.exists():
            part = path.with_suffix(path.suffix+'.part')
            offset = part.stat().st_size if part.exists() else 0
            request = urllib.request.Request(entry['url'], headers={'Range': f'bytes={offset}-'} if offset else {})
            begin = time.monotonic()
            with urllib.request.urlopen(request, timeout=45) as response:
                if offset and (response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-')):
                    raise ValueError('Server did not confirm resume range; partial preserved')
                with part.open('ab' if offset else 'wb') as out:
                    count, last = offset, time.monotonic()
                    while chunk := response.read(1024*1024):
                        count += len(chunk)
                        if count > entry['size']:
                            raise ValueError('Download exceeds pinned size')
                        out.write(chunk)
                        if time.monotonic()-last > 20:
                            print(json.dumps({'file': path.name, 'bytes': count, 'total': entry['size']}), flush=True)
                            last = time.monotonic()
            if count != entry['size']:
                raise ValueError('Incomplete download; partial preserved')
            part.replace(path)
            print(json.dumps({'downloaded': path.name, 'seconds': time.monotonic()-begin}), flush=True)
        size = path.stat().st_size
        if entry['algorithm'] == 'sha256':
            checksum = sha256(path)
        else:
            raw = path.read_bytes()
            checksum = hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw, usedforsecurity=False).hexdigest()
        if size != entry['size'] or checksum != entry['checksum']:
            raise ValueError('Publisher checksum mismatch')
        evidence.append(entry | {'actual_sha256': sha256(path), 'status': 'CHECKSUM_VERIFIED'})
        print(json.dumps({'verified': path.name, 'bytes': size}), flush=True)
    result = {'status': 'ACQUIRED', 'files': evidence, 'license': 'CC-BY-4.0',
              'fleurs_speaker_partition_basis': 'Publisher declares train speakers different from dev/test; IDs unavailable.',
              'publisher_cards_sha256': {n: sha256(ROOT / f'{n}-README.md') for n in SOURCES},
              'source_plan_sha256': sha256(plan_path), 'test_downloaded': False, 'training_executed': False}
    (ROOT / 'training-support-acquisition.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('Training source files acquired and verified', flush=True)


if __name__ == '__main__':
    acquire()

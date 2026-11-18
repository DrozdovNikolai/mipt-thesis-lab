"""Acquire four complete SOTERIA DVR files chosen by metadata, with resumable checks."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/soteria-v14'
DATA = ROOT / 'data/input/soteria-v14'
INVENTORY = ROOT / 'reports/direct-data-search-v1/soteria-inventory/media.json'
CREWS = {'Crew_01': 'train', 'Crew_02': 'dev', 'Crew_03': 'train', 'Crew_04': 'dev'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('Existing artifact differs: ' + str(path))
        return
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def plan():
    rows = json.loads(INVENTORY.read_text(encoding='utf-8'))
    chosen = []
    for crew, split in CREWS.items():
        candidates = [r for r in rows if r['key'].startswith(crew + '/DVR/')
                      and re.search(r'_Case_[123567]_', r['key'])
                      and r['key'].endswith('.mp4') and r['size'] >= 512 * 1024**2]
        row = min(candidates, key=lambda r: (r['size'], r['key']))
        chosen.append({**row, 'crew': crew, 'split': split,
                       'case': int(re.search(r'_Case_(\d+)_', row['key'])[1]),
                       'filename': crew + '-' + Path(row['key']).name})
    value = {
        'version': 14, 'source': 'NASA SOTERIA Simulation Testbed Data',
        'registry': 'https://registry.opendata.aws/nasa-soteria-data/',
        'license': 'CC-BY-4.0', 'inventory_sha256': sha(INVENTORY),
        'selection': 'First four crew IDs; smallest full DVR candidate >=512 MiB in cases 1,2,3,5,6,7; no ASR or audio-based selection',
        'sources': chosen, 'total_bytes': sum(r['size'] for r in chosen),
        'split_note': 'Provisional crew split only. Shared ATC/research actors may cross crews: requires scope/role verification before training or independent evaluation.',
        'unselected_crews': 'Not accessed in this experiment; no final test created',
        'drafts': 'User-authorized machine drafts; no automatic human attestations',
        'purpose': 'Corpus preparation and ASR disagreement diagnostics, not WER measurement',
    }
    assert value['total_bytes'] <= 6 * 1024**3
    save(REPORT / 'acquisition-plan.json', value)
    print(json.dumps({'files': len(chosen), 'GB': value['total_bytes']/1e9,
                      'sources': [{'crew': r['crew'], 'split': r['split'], 'case': r['case']} for r in chosen]}), flush=True)
    return value


def acquire(row):
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / row['filename']
    partial = path.with_suffix('.mp4.partial')
    report = REPORT / 'acquisition' / (row['crew'] + '.json')
    if report.exists():
        previous = json.loads(report.read_text(encoding='utf-8'))
        if path.stat().st_size != row['size'] or sha(path) != previous['sha256']:
            raise ValueError('Previously acquired file changed')
        return previous
    url = 'https://nasa-soteria-data.s3.us-west-2.amazonaws.com/' + urllib.parse.quote(row['key'])
    started, last_progress = time.monotonic(), 0.0
    if not path.exists():
        for attempt in range(8):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset == row['size']:
                break
            if offset > row['size']:
                raise ValueError('Partial file exceeds expected size')
            headers = {'If-Match': row['etag'], 'Range': f'bytes={offset}-', 'User-Agent': 'SOTERIA-research-import/14'}
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
                    if response.status != 206 or response.headers.get('ETag') != row['etag']:
                        raise ValueError('Expected immutable byte range response')
                    if response.headers.get('Content-Range') != f'bytes {offset}-{row["size"]-1}/{row["size"]}':
                        raise ValueError('Unexpected source range')
                    with partial.open('ab') as stream:
                        while block := response.read(1024 * 1024):
                            offset += len(block)
                            if offset > row['size']:
                                raise ValueError('Source length changed')
                            stream.write(block)
                            if time.monotonic() - last_progress >= 20:
                                print(json.dumps({'crew': row['crew'], 'downloaded_MB': round(offset/1e6),
                                                  'total_MB': round(row['size']/1e6)}), flush=True)
                                last_progress = time.monotonic()
                if offset == row['size']:
                    break
            except (OSError, TimeoutError) as error:
                print(json.dumps({'crew': row['crew'], 'attempt': attempt+1,
                                  'retry': type(error).__name__}), flush=True)
                if attempt == 7:
                    raise
                time.sleep(min(2**attempt, 15))
        if not partial.exists() or partial.stat().st_size != row['size']:
            raise ValueError('Incomplete source; partial retained')
        partial.rename(path)
    parts, h = [], hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024**2):
            h.update(block)
            parts.append(hashlib.md5(block).digest())
    multipart = hashlib.md5(b''.join(parts)).hexdigest() + '-' + str(len(parts))
    if path.stat().st_size != row['size'] or multipart != row['etag'].strip('"'):
        raise ValueError('Multipart checksum mismatch; original retained')
    value = {**row, 'url': url, 'sha256': h.hexdigest(), 'multipart_etag_verified': True,
             'seconds': round(time.monotonic()-started, 3), 'local_path': str(path.relative_to(ROOT)).replace('\\', '/')}
    save(report, value)
    print(json.dumps({'crew': row['crew'], 'status': 'verified', 'bytes': row['size']}), flush=True)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['plan', 'acquire'])
    args = parser.parse_args()
    p = plan()
    if args.stage == 'acquire':
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(acquire, p['sources']))
        save(REPORT / 'acquisition.json', {'plan_sha256': sha(REPORT/'acquisition-plan.json'), 'sources': results})
        (DATA/'SOURCE.txt').write_text('NASA SOTERIA Simulation Testbed Data. Accessed 2026-09-16.\n'
            'https://registry.opendata.aws/nasa-soteria-data/\nCC BY 4.0: https://creativecommons.org/licenses/by/4.0/\n'
            'Four DVR originals preserved. Derivatives: audio extraction, mono resampling, speech segmentation.\n'
            'Machine drafts are not human transcripts. Crew_01/03 provisional train, Crew_02/04 dev.\n', encoding='utf-8')


if __name__ == '__main__':
    main()

"""Acquire and safely extract reviewed BLeRIOT-B v1 acoustic assets."""

import json
import shutil
import subprocess
from pathlib import Path

import acquire_bleriot
from extract_bleriot import parse_listing, safe_member


def main():
    root = Path('data/input/bleriot')
    source = root / 'bleriot-b'
    acquire_bleriot.SOURCES['B'] = ('NODS6L', 738998, 47053587, '0f2a3f1ef2550df3ae9a6f62b26db9c4')
    evidence = acquire_bleriot.acquire('B', root)
    seven_zip = shutil.which('7zz') or shutil.which('7z') or 'C:/Program Files/7-Zip/7z.exe'
    reports = []
    for archive in evidence['files']:
        if not archive['filename'].endswith('.rar'):
            continue
        path = source / archive['filename']
        destination = (root / 'verified/b-v1' / path.stem).resolve()
        report_path = destination / 'extraction.json'
        if report_path.exists():
            report = json.loads(report_path.read_text())
            if report['archive_sha256'] != archive['sha256'] or any(acquire_bleriot.hashes(destination / e['path'])['sha256'] != e['sha256'] for e in report['entries']):
                raise ValueError('Completed extraction changed')
            reports.append(report)
            continue
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('Extraction requires an empty destination')
        destination.mkdir(parents=True, exist_ok=True)
        listing = subprocess.check_output([seven_zip, 'l', '-slt', '-sccUTF-8', str(path.resolve())], encoding='utf-8', timeout=180).replace('\r\n', '\n')
        entries = parse_listing(listing, destination)
        subprocess.run([seven_zip, 'x', '-y', '-bd', '-bso0', f'-o{destination.resolve()}', str(path.resolve())], check=True, timeout=300)
        actual = []
        for entry in entries:
            extracted = safe_member(entry['Path'], destination)
            if extracted.is_symlink() or (hasattr(extracted, 'is_junction') and extracted.is_junction()):
                raise ValueError('Extracted link')
            if extracted.is_dir():
                continue
            if not extracted.is_file() or extracted.stat().st_size != int(entry['Size']):
                raise ValueError('Extracted file size differs')
            actual.append({'path': extracted.relative_to(destination).as_posix(), 'bytes': extracted.stat().st_size, **acquire_bleriot.hashes(extracted)})
        report = {'archive_sha256': archive['sha256'], 'archive': archive['filename'], 'entries': actual, 'license': evidence['license_id'], 'human_scope_verified': False, 'primary_quality_admitted': False}
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        reports.append(report)
    output = Path('reports/additional-sources-v1')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'bleriot-b-acquisition.json').write_text(json.dumps({'acquisition': evidence, 'extractions': reports}, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'ACQUIRED_EXTRACTED', 'archives': len(reports), 'files': sum(len(r['entries']) for r in reports)}))


if __name__ == '__main__':
    main()

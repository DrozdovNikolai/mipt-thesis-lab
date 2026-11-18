"""Reproduce the reviewed Noort supplement acquisition and metadata-only split.

The download hash pins the already acquired specimen; it is not a publisher
checksum. Existing acquisition/partition evidence is checked, never rewritten.
No transcript or label is printed or used to decide a case assignment.
"""

import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

from scripts.prepare_cvr_native import partition

URL = 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8627982/supplementaryFiles'
SIZE = 4711764
ZIP_SHA256 = 'd5f88a3c0c0148945be81310f79be3f95c6b28e1b12defc1db804eca7dfd67ac'
XML_SHA256 = 'e1c5e56d24ffa1f51e65db1fb855bb71e7f31a10ab179968f0a5e3a8e215f732'
CSV_SHA256 = '906e5020e59f5d3df3e5da383f4d2b4f917b1f3d944bae4dd16eb381b8e04120'


def sha(content):
    return hashlib.sha256(content).hexdigest()


def main():
    root = Path('data/input/cvr-noort-v1')
    root.mkdir(parents=True, exist_ok=True)
    license_xml = Path('reports/additional-sources-v1/discovery/cvr-data-xml.response')
    if sha(license_xml.read_bytes()) != XML_SHA256:
        raise ValueError('Reviewed primary-source license evidence changed or is missing')
    target = root / 'supplementary.zip'
    downloaded = not target.exists()
    if downloaded:
        partial = target.with_suffix('.zip.part')
        with urllib.request.urlopen(URL, timeout=45) as response, partial.open('xb') as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > SIZE:
                    raise ValueError('Source is larger than the pinned specimen')
                output.write(chunk)
        if count != SIZE or sha(partial.read_bytes()) != ZIP_SHA256:
            raise ValueError('Source changed; preserve partial file for investigation')
        partial.replace(target)
    content = target.read_bytes()
    if len(content) != SIZE or sha(content) != ZIP_SHA256:
        raise ValueError('Acquired supplement differs from reviewed specimen')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        info = archive.getinfo('mmc2.csv')
        if info.file_size != 44486986:
            raise ValueError('Unexpected decompressed size')
        raw = archive.read(info)
    if sha(raw) != CSV_SHA256:
        raise ValueError('Raw publisher table changed')
    cases = {r['case_id'] for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))}
    expected = {'method': 'sha256_55_case_id_mod100_70_15_15_before_text_inspection',
        'source_sha256': CSV_SHA256, 'assignments': {case: partition(case) for case in sorted(cases)},
        'test_text_inspected': False, 'test_labels_inspected': False}
    split_path = root / 'case-partition.json'
    if split_path.exists():
        if json.loads(split_path.read_bytes()) != expected:
            raise ValueError('Preserved partition differs; do not rebalance after evaluation')
    else:
        with split_path.open('x', encoding='utf-8') as output:
            output.write(json.dumps(expected, indent=2))
    provenance = {'url': URL, 'status': 200, 'content_type': 'application/zip', 'bytes': SIZE,
        'sha256': ZIP_SHA256,
        'license_basis': 'CC BY 4.0 article and associated supplementary data; preserve source attribution and any narrower file notice',
        'license_xml_sha256': XML_SHA256}
    acquisition = root / 'acquisition.json'
    if acquisition.exists():
        if json.loads(acquisition.read_bytes()) != provenance:
            raise ValueError('Existing acquisition provenance differs')
    else:
        with acquisition.open('x', encoding='utf-8') as output:
            output.write(json.dumps(provenance, indent=2))
    print(json.dumps({'status': 'VERIFIED', 'downloaded_now': downloaded, 'cases': len(cases),
        'supplement_sha256': sha(content), 'partition_sha256': sha(split_path.read_bytes()),
        'acquisition_sha256': sha(acquisition.read_bytes()), 'script_sha256': sha(Path(__file__).read_bytes()),
        'attribution': 'Noort, Reader & Gillespie (2021), doi:10.1016/j.dib.2021.107602',
        'license': 'CC-BY-4.0', 'labels_created': False, 'project_labels_inferred': False}))


if __name__ == '__main__':
    main()

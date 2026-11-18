"""Persist public metadata for additional sources; no automatic gold admission."""

import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

URLS = {
    'bleriot-b': 'https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/NODS6L',
    'cvr-data-xml': 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8627982/fullTextXML',
    'ears-data-xml': 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12560795/fullTextXML',
    'dlr-new-page': 'https://elib.dlr.de/219140/',
    'dlr-new-paper': 'https://elib.dlr.de/219140/1/650258.pdf',
    'pilot-false-positive': 'https://huggingface.co/datasets/Oye12/A_Pilot_Speech_Corpus/raw/main/README.md',
    'golos-card': 'https://raw.githubusercontent.com/sberdevices/golos/master/README.md',
    'golos-license': 'https://raw.githubusercontent.com/sberdevices/golos/master/license/en_us.pdf',
    'fleurs-api': 'https://huggingface.co/api/datasets/google/fleurs',
    'fleurs-card': 'https://huggingface.co/datasets/google/fleurs/raw/main/README.md',
    'mdpi-crew-commands': 'https://www.mdpi.com/2076-3417/16/7/3461',
}


def main():
    root = Path('reports/additional-sources-v1/discovery')
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'retrieval.json').exists():
        raise ValueError('Preserve the completed audit')

    def fetch(item):
        key, url = item
        record = {'id': key, 'url': url, 'checked_at': datetime.now(UTC).isoformat()}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'north55-research/1.0'}), timeout=30) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError('Metadata size limit')
                (root / f'{key}.response').write_bytes(data)
                record.update(status=response.status, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), final_url=response.url)
        except (OSError, ValueError) as exc:
            record.update(status=getattr(exc, 'code', None), error=f'{type(exc).__name__}: {exc}')
        return record

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, URLS.items()))
    (root / 'retrieval.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps([{k: v for k, v in r.items() if k in ('id', 'status', 'bytes', 'error')} for r in records], indent=2))


if __name__ == '__main__':
    main()

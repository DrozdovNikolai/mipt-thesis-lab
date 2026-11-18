"""Acquire only official Russian FLEURS dev files for general speech controls."""

import hashlib
import json
import urllib.request
from pathlib import Path

REVISION = '70bb2e84b976b7e960aa89f1c648e09c59f894dd'
FILES = {
    'audio/dev.tar.gz': (187377526, '4dc533cd0f312f749bd6d0fe968f3183288d938e07ed97dc141d9f10570457f9', 'sha256'),
    'dev.tsv': (316328, '8e6be8c301fcdf2df3a99219c9c6ab643cf10e36', 'git_blob_sha1'),
}


def main():
    root = Path('data/input/fleurs-ru-v1')
    root.mkdir(parents=True, exist_ok=True)
    card = Path('reports/additional-sources-v1/discovery/fleurs-api.response')
    metadata = json.loads(card.read_bytes())
    if metadata['sha'] != REVISION or metadata['cardData']['license'] != ['cc-by-4.0']:
        raise ValueError('Reviewed revision/license changed')
    evidence = []
    for name, (size, expected, algorithm) in FILES.items():
        path = root / Path(name).name
        url = f'https://huggingface.co/datasets/google/fleurs/resolve/{REVISION}/data/ru_ru/{name}'
        if not path.exists():
            partial = path.with_suffix(path.suffix + '.part')
            with urllib.request.urlopen(url, timeout=45) as response, partial.open('wb') as output:
                count = 0
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > size:
                        raise ValueError('Download exceeds frozen source size')
                    output.write(chunk)
            if count != size:
                raise ValueError('Incomplete source download')
            partial.replace(path)
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest() if algorithm == 'sha256' else hashlib.sha1(f'blob {len(content)}\0'.encode() + content, usedforsecurity=False).hexdigest()
        if len(content) != size or checksum != expected:
            raise ValueError('Pinned publisher checksum mismatch')
        evidence.append({'path': path.name, 'url': url, 'bytes': size, 'publisher_algorithm': algorithm, 'publisher_checksum': expected, 'sha256': hashlib.sha256(content).hexdigest()})
        print(json.dumps(evidence[-1]), flush=True)
    result = {'source': 'Google FLEURS', 'revision': REVISION, 'license': 'CC-BY-4.0', 'attribution': 'Conneau et al., FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech, 2022', 'role': 'general_RU_development_controls_only', 'source_split': 'dev', 'local_human_audio_audit': False, 'speaker_ids_available': False, 'test_downloaded': False, 'files': evidence}
    (root / 'acquisition.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

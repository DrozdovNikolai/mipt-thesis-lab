"""Prepare new BLeRIOT-B noise channels and fixed general Russian controls."""

import csv
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from north55_speech.core import atomic_json, file_hash, now, settings


def main():
    root = Path('/additional-audio')
    if (root / 'plan.json').exists():
        raise ValueError('Preserve the frozen audio plan')
    b = Path('/b')
    items, references, inventory = [], {}, []
    for archive in sorted(b.glob('*/extraction.json')):
        extraction = json.loads(archive.read_bytes())
        for entry in extraction['entries']:
            path = archive.parent / entry['path']
            if file_hash(path) != entry['sha256']:
                raise ValueError('BLeRIOT-B extracted file changed')
            if path.suffix.lower() == '.wav':
                audio, rate = sf.read(path, dtype='float32', always_2d=True)
                if not len(audio) or not np.isfinite(audio).all():
                    raise ValueError('Invalid BLeRIOT-B WAV')
                inventory.append({'path': str(path.relative_to(b)), 'sha256': entry['sha256'], 'rate': rate, 'channels': audio.shape[1], 'duration_sec': len(audio) / rate})
                if archive.parent.name != 'flight-noise':
                    continue
                aircraft = 'A330-743' if 'A330-743' in entry['path'] else 'TBM940'
                for channel in range(audio.shape[1]):
                    waveform = resample_poly(audio[:, channel], 1, 3).astype(np.float32)
                    if rate != 48000:
                        raise ValueError('Unexpected noise source rate')
                    identifier = f'bnoise-{path.stem}-ch{channel}'
                    output = settings.audio_root / 'additional-audio-v1' / f'{identifier}.wav'
                    output.parent.mkdir(parents=True, exist_ok=True)
                    if output.exists():
                        raise ValueError('Prepared audio already exists')
                    sf.write(output, waveform, 16000, subtype='FLOAT')
                    items.append({'id': identifier, 'audio_path': str(output.relative_to(settings.audio_root)), 'audio_sha256': file_hash(output),
                        'source_sha256': entry['sha256'], 'source_channel': channel, 'source_rate': rate,
                        'group_id': f'bleriot-b-aircraft-{aircraft}', 'duration_sec': len(waveform) / 16000,
                        'input_language': 'auto', 'cohort': 'bleriot_b_noise', 'reference_kind': 'publisher_flight_noise_not_independently_audited',
                        'primary': False, 'scope_verified': False, 'split': 'dev', 'license': 'CC-BY-NC-4.0'})
                    references[identifier] = ''
            elif path.suffix.lower() == '.npy':
                coefficients = np.load(path, allow_pickle=False)
                if not np.issubdtype(coefficients.dtype, np.number) or not np.isfinite(coefficients).all():
                    raise ValueError('Invalid numeric impulse coefficients')
                inventory.append({'path': str(path.relative_to(b)), 'sha256': entry['sha256'], 'shape': list(coefficients.shape), 'dtype': str(coefficients.dtype)})
            else:
                raise ValueError('Unexpected BLeRIOT-B member type')
    fleurs = Path('/fleurs')
    acquisition = json.loads((fleurs / 'acquisition.json').read_bytes())
    if any(file_hash(fleurs / f['path']) != f['sha256'] for f in acquisition['files']):
        raise ValueError('FLEURS acquired bytes changed')
    with (fleurs / 'dev.tsv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.reader(stream, delimiter='\t'))
    if any(len(r) != 7 for r in rows):
        raise ValueError('Unexpected official FLEURS TSV format')
    # Choose one file per sentence ID by hashes alone, then 50 IDs; no ASR outcome.
    by_id = {}
    for r in sorted(rows, key=lambda r: hashlib.sha256(('55:' + r[1]).encode()).hexdigest()):
        by_id.setdefault(r[0], r)
    chosen = sorted(by_id, key=lambda key: hashlib.sha256(('55:fleurs-ru:' + key).encode()).hexdigest())[:50]
    selected = {by_id[k][1]: by_id[k] for k in chosen}
    seen = set()
    with tarfile.open(fleurs / 'dev.tar.gz', 'r:gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or member.issym() or member.islnk():
                raise ValueError('Unsafe FLEURS archive member')
            if not member.isfile() or name.name not in selected:
                continue
            if name.name in seen or member.size > 20 * 1024 * 1024:
                raise ValueError('Duplicate/oversized selected FLEURS member')
            seen.add(name.name)
            content = archive.extractfile(member).read()
            waveform, rate = sf.read(io.BytesIO(content), dtype='float32')
            row = selected[name.name]
            if rate != 16000 or waveform.ndim != 1 or len(waveform) != int(row[5]) or not np.isfinite(waveform).all():
                raise ValueError('FLEURS audio/TSV mismatch')
            identifier = f'fleurs-ru-{row[0]}'
            output = settings.audio_root / 'additional-audio-v1' / f'{identifier}.wav'
            if output.exists():
                raise ValueError('Prepared audio already exists')
            sf.write(output, waveform, rate, subtype='FLOAT')
            items.append({'id': identifier, 'audio_path': str(output.relative_to(settings.audio_root)), 'audio_sha256': file_hash(output),
                'original_audio_sha256': hashlib.sha256(content).hexdigest(), 'group_id': 'fleurs-ru-unknown-speakers-dev',
                'duration_sec': len(waveform) / rate, 'input_language': 'ru', 'cohort': 'general_ru',
                'reference_kind': 'publisher_human_read_transcript_general_RU', 'primary': False, 'scope_verified': False,
                'split': 'dev', 'license': 'CC-BY-4.0', 'speaker_ids_known': False})
            references[identifier] = row[3]
    if set(selected) != seen:
        raise ValueError('Missing selected FLEURS audio')
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / 'references.json', references)
    atomic_json(root / 'plan.json', {'created_at': now().isoformat(), 'script_sha256': file_hash(Path(__file__)),
        'items': items, 'references_sha256': file_hash(root / 'references.json'), 'bleriot_b_inventory': inventory,
        'fleurs_selection': {'algorithm': 'seed55_hash_sentence_then_one_recording_per_id', 'sentence_ids': chosen, 'source_split': 'dev'},
        'quality_evidence': False, 'noise_training_admitted': False, 'test_accessed': False,
        'limitations': ['B noise microphones/channels are correlated; conservative grouping by aircraft, only two groups.',
            'Flight noise has publisher provenance, no independent human speech-absence audit.',
            'FLEURS is general read Russian, no speaker identifiers, one conservative group, no cabin claim.',
            'Impulse responses validated as data, not used to simulate independent recordings.']})
    print(json.dumps({'status': 'PREPARED', 'noise_channels': sum(i['cohort'] == 'bleriot_b_noise' for i in items), 'russian_controls': len(chosen), 'b_files_verified': len(inventory)}))


if __name__ == '__main__':
    main()

"""Inspect public candidate files; no ASR, training, or benchmark admission."""
import hashlib
import io
import json
from pathlib import Path
import wave

import pyarrow.parquet as pq


def inspect(root: Path) -> dict:
    files = []
    all_pcm_hashes = []
    for path in sorted(root.glob('*.parquet')):
        blob = path.read_bytes()
        table = pq.read_table(path)
        groups = {}
        empty_texts = 0
        pcm_hashes = []
        formats = set()
        for row in table.to_pylist():
            audio = row['audio']['bytes']
            with wave.open(io.BytesIO(audio), 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
                fmt = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
                formats.add(fmt)
                pcm = wav.readframes(wav.getnframes())
                pcm_hashes.append(hashlib.sha256(repr(fmt).encode() + pcm).hexdigest())
            group = row['id'].split('_')[0]
            totals = groups.setdefault(group, {'rows': 0, 'seconds': 0.0})
            totals['rows'] += 1
            totals['seconds'] += duration
            empty_texts += not bool((row['text'] or '').strip())
        all_pcm_hashes.extend(pcm_hashes)
        files.append({
            'file': path.name,
            'bytes': len(blob),
            'sha256': hashlib.sha256(blob).hexdigest(),
            'git_blob_sha1': hashlib.sha1(f'blob {len(blob)}\0'.encode() + blob).hexdigest(),
            'columns': table.column_names,
            'rows': table.num_rows,
            'seconds': sum(g['seconds'] for g in groups.values()),
            'groups_by_filename_not_verified_speakers': groups,
            'audio_formats_rate_channels_samplewidth': sorted(formats),
            'unique_pcm_hashes': len(set(pcm_hashes)),
            'empty_texts': empty_texts,
        })
    return {
        'repository': 'wangyubo013-blip/CDE4301-VR-401-Final-Report',
        'revision': '0c520edbcd345cb9005cc77c3345eedbfef7147b',
        'files': files,
        'total_rows': sum(f['rows'] for f in files),
        'total_seconds': sum(f['seconds'] for f in files),
        'unique_pcm_hashes_across_files': len(set(all_pcm_hashes)),
        'rights_for_training_confirmed': False,
        'local_human_transcript_verification': False,
        'speaker_independence_verified': False,
        'scope': 'mixed cockpit and ATC examples; no sample admitted to project benchmark',
        'asr_or_training_executed': False,
    }


if __name__ == '__main__':
    print(json.dumps(inspect(Path('/audit')), ensure_ascii=False, indent=2))

"""Import bounded publisher-labelled EN/RU train pairs without manual transcription."""

import csv
import hashlib
import io
import json
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, file_hash, settings
from north55_speech.datasets import Sample, decoded_audio_hash, validate_groups, write_manifest

ROOT = Path('/support')
OUTPUT = Path('/prepared')


def read(path):
    return json.loads(path.read_bytes())


def fleurs_rows(path):
    # Publisher TSV uses literal quotation marks, not RFC CSV quoting.
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.reader(stream, delimiter='\t', quoting=csv.QUOTE_NONE))
    if any(len(row) != 7 for row in rows):
        raise ValueError('Unexpected FLEURS TSV format')
    return rows


def waveform(content):
    audio, rate = sf.read(io.BytesIO(content), dtype='float32')
    if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError('Expected finite mono 16 kHz publisher audio')
    return audio


def make_sample(identifier, audio, text, language, speaker, original, chapter, source, revision, original_sha):
    path = settings.audio_root / 'training-support-v1' / f'{identifier}.wav'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        previous, rate = sf.read(path, dtype='float32')
        if rate != 16000 or not np.array_equal(previous, audio):
            raise ValueError('Existing support audio changed')
    else:
        sf.write(path, audio, 16000, subtype='FLOAT')
    return Sample(
        sample_id=identifier, audio_path=str(path.relative_to(settings.audio_root)),
        audio_sha256=file_hash(path), decoded_audio_sha256=decoded_audio_hash([path]),
        source_dataset=source, source_version=revision, recording_id=original,
        session_id=chapter, original_utterance_id=original, speaker_ids=[speaker] if speaker else [],
        language=language, input_language=language, scope='general_control', scope_verified=False,
        speech_origin='recorded_human', duration_sec=len(audio)/16000,
        license_id='CC-BY-4.0', provenance=f'https://huggingface.co/datasets/{source}/tree/{revision}',
        rights_confirmed=True, transcript_status='human_verified', reference_text=text,
        primary=False, clean_control=False, split='train',
        annotation_provenance={'method': 'publisher_supervised_corpus_import',
            'annotator': source, 'reviewed_audio': False, 'local_manual_verification': False,
            'verification_scope': 'publisher_provided_human_reference_not_local_audio_audit',
            'source_split': 'train', 'original_audio_sha256': original_sha,
            'acquisition_sha256': file_hash(ROOT / 'training-support-acquisition.json'),
            'speaker_partition_basis': 'explicit LibriSpeech IDs' if speaker else
                'FLEURS publisher train/dev speaker-disjointness; all RU train in one conservative group'}
    )


def main():
    import pyarrow.parquet as pq

    acquisition = read(ROOT / 'training-support-acquisition.json')
    plan = read(ROOT / 'training-support-plan.json')
    if acquisition['status'] != 'ACQUIRED' or acquisition['license'] != 'CC-BY-4.0':
        raise ValueError('Verified acquisition required')
    if file_hash(ROOT / 'training-support-plan.json') != acquisition['source_plan_sha256']:
        raise ValueError('Acquisition plan changed')
    for entry in acquisition['files']:
        if file_hash(ROOT / entry['local']) != entry['actual_sha256']:
            raise ValueError('Acquired source changed')
    controls = read(Path('/clean-plan.json'))['items']
    excluded_speakers = {str(i['speaker_id']) for i in controls}
    excluded_hashes = {i['decoded_float32_sha256'] for i in controls}
    ru_controls = read(Path('/additional-plan.json'))['items']
    # Controls are used only to enforce disjoint IDs/hashes, never to select by answers.
    for item in ru_controls:
        if item['cohort'] == 'general_ru':
            audio, _ = sf.read(settings.audio_root / item['audio_path'], dtype='float32')
            excluded_hashes.add(hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest())
    ru_dev_ids = {r[0] for r in fleurs_rows(Path('/fleurs-dev.tsv'))}
    samples, excluded, seen_pcm = [], Counter(), set(excluded_hashes)
    limit = plan['limit_per_language']
    revisions = {k: v['revision'] for k, v in plan['sources'].items()}
    for batch in pq.ParquetFile(ROOT / 'librispeech-0000.parquet').iter_batches(batch_size=32):
        for row in batch.to_pylist():
            if sum(s.language == 'en' for s in samples) >= limit:
                break
            if str(row['speaker_id']) in excluded_speakers:
                raise ValueError('LibriSpeech train speaker overlaps existing control')
            content = row['audio']['bytes']
            audio = waveform(content)
            if not row['text'].strip() or not 16000 <= len(audio) <= 30*16000:
                excluded['EN_empty_text_or_duration'] += 1
                continue
            pcm = hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest()
            if pcm in seen_pcm:
                excluded['EN_duplicate_audio'] += 1
                continue
            seen_pcm.add(pcm)
            samples.append(make_sample('libri-train-'+row['id'], audio, row['text'], 'en',
                'librispeech-reader-'+str(row['speaker_id']), 'librispeech-'+row['id'],
                'librispeech-chapter-'+str(row['chapter_id']), 'openslr/librispeech_asr',
                revisions['librispeech'], hashlib.sha256(content).hexdigest()))
        if sum(s.language == 'en' for s in samples) >= limit:
            break
    rows = fleurs_rows(ROOT / 'fleurs-train.tsv')
    if {r[0] for r in rows} & ru_dev_ids:
        raise ValueError('FLEURS train/dev share original sentence IDs')
    selected, seen_ids = {}, set()
    for row in rows:
        if len(selected) >= limit:
            break
        if row[0] in seen_ids or not row[3].strip() or not 16000 <= int(row[5]) <= 30*16000:
            excluded['RU_repeated_sentence_or_duration'] += 1
            continue
        selected[row[1]] = row
        seen_ids.add(row[0])
    seen_names = set()
    with tarfile.open(ROOT / 'fleurs-train.tar.gz', 'r:gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or member.issym() or member.islnk():
                raise ValueError('Unsafe archive entry')
            if not member.isfile() or name.name not in selected:
                continue
            if name.name in seen_names or member.size > 20*1024*1024:
                raise ValueError('Duplicate or oversized selected archive member')
            seen_names.add(name.name)
            content = archive.extractfile(member).read()
            audio, row = waveform(content), selected[name.name]
            if len(audio) != int(row[5]):
                raise ValueError('FLEURS audio/metadata length mismatch')
            pcm = hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest()
            if pcm in seen_pcm:
                raise ValueError('Selected Russian training waveform overlaps another waveform')
            seen_pcm.add(pcm)
            samples.append(make_sample('fleurs-ru-train-'+row[0], audio, row[3], 'ru', None,
                'fleurs-ru-sentence-'+row[0], 'fleurs-ru-train-unknown-speakers', 'google/fleurs',
                revisions['fleurs'], hashlib.sha256(content).hexdigest()))
    if seen_names != set(selected):
        raise ValueError('Missing selected training audio')
    samples.sort(key=lambda s: s.sample_id)
    groups = validate_groups(samples)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = OUTPUT / 'train.jsonl'
    expected = ''.join(s.model_dump_json()+'\n' for s in samples).encode('utf-8')
    if manifest.exists() and manifest.read_bytes() != expected:
        raise ValueError('Support manifest changed on reproduction')
    write_manifest(manifest, samples)
    report = {'status': 'PREPARED_PUBLISHER_REFERENCES', 'languages': dict(Counter(s.language for s in samples)),
              'minutes': {lang: sum(s.duration_sec for s in samples if s.language == lang)/60 for lang in ('en', 'ru')},
              'known_en_speakers': len({v for s in samples for v in s.speaker_ids}),
              'groups': groups, 'source_rows_examined_by_model': 0, 'exclusions': dict(excluded),
              'manifest_sha256': file_hash(manifest), 'script_sha256': file_hash(Path(__file__)),
              'acquisition_sha256': file_hash(ROOT / 'training-support-acquisition.json'),
              'dev_speakers_ids_and_waveform_duplicates_checked': True,
              'source_transcripts_imported_without_rewriting': True,
              'local_human_audio_review': False, 'primary_cockpit_evidence': False,
              'training_executed': False, 'test_accessed': False, 'release_promoted': False,
              'attribution': ['Panayotov et al., LibriSpeech, ICASSP 2015; OpenSLR 12.',
                              'Conneau et al., FLEURS, 2022, arXiv:2205.12446.'],
              'limitations': ['Publisher annotation quality is inherited, not locally verified.',
                              'General read speech is supplementary training, not a cabin quality test.',
                              'FLEURS IDs do not identify speakers; conservative single RU train group.',
                              'Mixed EN/RU is not represented by separate monolingual recordings.']}
    atomic_json(OUTPUT / 'report.json', report)
    atomic_json(Path('/study/training-support.json'), report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

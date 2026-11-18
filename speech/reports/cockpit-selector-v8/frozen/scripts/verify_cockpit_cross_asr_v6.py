"""Verify delivered artifacts and reproduce error totals without the report scorer."""
import json
from pathlib import Path

import soundfile as sf
from rapidfuzz.distance import Levenshtein

from north55_speech.core import file_hash
from north55_speech.datasets import Sample, validate_groups
from north55_speech.metrics import lexical_normalizer_v1
from scripts.cockpit_cross_asr_v6 import EXP, STUDY, SYSTEMS, pcm, read, save


def main():
    plan = read(STUDY/'inference/plan.json')
    result = read(STUDY/'comparison.json')
    inputs = read(STUDY/'inference/inputs.json')
    execution = read(STUDY/'predictions/execution.json')
    refs, historical = read(STUDY/'scoring/references.json'), read(STUDY/'scoring/historical.json')
    counts = read(STUDY/'scored-counts.json')
    assert result['plan_sha256'] == execution['plan_sha256'] == file_hash(STUDY/'inference/plan.json')
    assert len(inputs) == len(execution['prediction_sha256']) == 843
    assert execution['device'] == 'cuda:0' and execution['precision'] == 'torch.float32'
    assert execution['new_ASR_calls'] == 843 and not execution['failures']
    assert file_hash(STUDY/'protocol.md') == plan['protocol_sha256']
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(STUDY/'frozen'/name) == digest
    for name, digest in plan['scoring_sha256'].items():
        assert file_hash(STUDY/'scoring'/name) == digest
    amendment = read(STUDY/'runtime-amendment-r2/amendment.json')
    assert file_hash(STUDY/'runtime-amendment-r2/run_parakeet_v6.py') == amendment['runner_sha256']
    assert amendment['plan_sha256'] == result['plan_sha256'] and not amendment['decoding_changed']
    checked_scores = 0
    for item in inputs:
        path = EXP/item['audio_path']
        assert path.resolve().is_relative_to(EXP/'input-audio') and file_hash(path) == item['audio_sha256']
        x, rate = sf.read(path, dtype='float32')
        assert rate == 16000 and pcm(x) == item['pcm_sha256'] and len(x)/rate == item['duration_sec']
        prediction_path = STUDY/'predictions'/(item['id']+'.json')
        assert file_hash(prediction_path) == execution['prediction_sha256'][prediction_path.name]
        prediction = read(prediction_path)
        assert prediction['plan_sha256'] == result['plan_sha256'] and not prediction['error']
        assert prediction['precision'] == 'torch.float32' and prediction['device'] == 'cuda:0'
        identity = item['id']
        if identity in refs:
            a = lexical_normalizer_v1(refs[identity]).split()
            texts = {s: historical[identity][s]['hypothesis'] for s in SYSTEMS} | {'parakeet': prediction['hypothesis']}
            for system, text in texts.items():
                b = lexical_normalizer_v1(text).split()
                c = counts[identity][system+'-raw']
                assert Levenshtein.distance(a, b) == c['S']+c['D']+c['I']
                assert len(a) == c['N']
                checked_scores += 1
    datasets = STUDY/'datasets'
    combined = [Sample.model_validate_json(line) for line in (datasets/'combined-weak-train.jsonl').read_text(encoding='utf-8').splitlines()]
    supplemental = [Sample.model_validate_json(line) for line in (datasets/'supplemental-weak-train.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(combined) == 247+len(supplemental) and all(s.split == 'train' for s in combined)
    assert all(s.transcript_status == 'weak' and not s.annotation_provenance.get('human_verified') for s in supplemental)
    validate_groups(combined)
    old = {s['sample_id']: s for s in read(STUDY/'scoring/train.json')}
    for row in combined:
        if row.sample_id in old:
            assert row.reference_text == old[row.sample_id]['reference_text']
            assert row.audio_sha256 == old[row.sample_id]['audio_sha256']
    decisions = {d['id']: d for d in read(STUDY/'recovery-decisions.json')}
    assert len(decisions) == 352 and sum(d['accepted'] for d in decisions.values()) == len(supplemental)
    assert all(not result[k] for k in ('quality_evidence', 'release_promoted', 'test_accessed', 'blind_dev_accessed'))
    # Prior v5 frozen plan, inputs, references and model outputs were only read.
    prior = Path('/workspace/reports/cockpit-robust-v5')
    assert file_hash(prior/'plan.json') == plan['prior_plan_sha256']
    old_plan = read(prior/'plan.json')
    for name, digest in old_plan['implementation_sha256'].items():
        assert file_hash(prior/'frozen'/name) == digest
    for name, digest in plan['historical_execution_sha256'].items():
        assert file_hash(prior/('io-'+name)/'execution.json') == digest
    value = {'status': 'PASS', 'audio_files_verified': len(inputs), 'ASR_records_verified': execution['records'],
        'independent_levenshtein_totals_verified': checked_scores, 'supplemental_weak_rows': len(supplemental),
        'old_train_rows_preserved': len(old), 'prior_frozen_code_unchanged': True,
        'plan_sha256': result['plan_sha256'], 'verifier_sha256': file_hash(Path(__file__))}
    save(STUDY/'verification.json', value)
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()

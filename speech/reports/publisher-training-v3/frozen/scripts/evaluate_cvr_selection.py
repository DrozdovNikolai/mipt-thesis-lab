"""Select on dev, freeze, infer with text only, then score native-label holdout."""

import argparse
import json
from pathlib import Path

import skops.io as skops

from north55_speech.core import atomic_json, file_hash, now
from scripts.cvr_context_experiment import contextual_texts
from scripts.cvr_native_experiment import metrics, read_rows, rules

ROOT = Path('/result')


def code_hashes():
    return {str(p): file_hash(p) for p in [Path(__file__), Path('/app/scripts/cvr_native_experiment.py'),
        Path('/app/scripts/cvr_context_experiment.py'), Path('/app/src/north55_speech/nlp.py')]}


def freeze():
    if (ROOT / 'final-selection.json').exists():
        raise ValueError('Preserve final native selection')
    original = json.loads(Path('/original/selection.json').read_bytes())
    context = json.loads(Path('/context/selection.json').read_bytes())
    proof = json.loads(Path('/proof/preparation.json').read_bytes())
    chosen = 'context' if context['chosen']['metrics']['macro_f1'] > original['chosen']['metrics']['macro_f1'] else 'original'
    source = Path('/' + chosen)
    selection = context if chosen == 'context' else original
    if file_hash(source / 'model.skops') != selection['model_sha256']:
        raise ValueError('Selected model changed')
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'model.skops').write_bytes((source / 'model.skops').read_bytes())
    result = {'frozen_at': now().isoformat(), 'chosen': chosen, 'threshold': selection['chosen']['threshold'],
        'model_sha256': selection['model_sha256'], 'code_sha256': code_hashes(),
        'source_selection_sha256': {s: file_hash(Path('/' + s) / 'selection.json') for s in ('original', 'context')},
        'source_dev_scores': {'original': original['chosen']['metrics'], 'context': context['chosen']['metrics'], **original['dev_rule_baselines']},
        'test_inputs_sha256': proof['files']['sealed/test-inputs.jsonl'], 'test_references_sha256': proof['files']['sealed/test-references.jsonl'],
        'source_native_only': True, 'candidate_trials': 12, 'rule_baselines': 2, 'project_event_gate': 'NEEDS_MORE_DATA', 'release_promoted': False,
        'known_holdout_cases_before_access': proof['splits']['test']['cases'], 'holdout_purpose': 'descriptive execution check only; insufficient independent cases for generalization'}
    atomic_json(ROOT / 'final-selection.json', result)
    print(json.dumps({'status': 'FROZEN_BEFORE_HOLDOUT_INFERENCE', 'chosen': chosen, 'holdout_cases': proof['splits']['test']['cases']}))


def validate():
    selection = json.loads((ROOT / 'final-selection.json').read_bytes())
    if selection['code_sha256'] != code_hashes() or selection['model_sha256'] != file_hash(ROOT / 'model.skops'):
        raise ValueError('Native selection changed')
    return selection


def infer():
    selection = validate()
    path = Path('/inputs/test-inputs.jsonl')
    if file_hash(path) != selection['test_inputs_sha256']:
        raise ValueError('Input holdout changed')
    if (ROOT / 'predictions.json').exists():
        raise ValueError('Preserve held-out predictions')
    rows = read_rows(path)
    if any(set(r) != {'id', 'group_id', 'text'} for r in rows):
        raise ValueError('Unexpected label/metadata in inference input')
    features = contextual_texts(rows) if selection['chosen'] == 'context' else [r['text'] for r in rows]
    if skops.get_untrusted_types(file=ROOT / 'model.skops'):
        raise ValueError('Unexpected estimator type')
    model = skops.load(ROOT / 'model.skops', trusted=[])
    scores = model.predict_proba(features)[:, 1]
    atomic_json(ROOT / 'predictions.json', {'executed_at': now().isoformat(), 'selection_sha256': file_hash(ROOT / 'final-selection.json'),
        'rows': [{'id': r['id'], 'group_id': r['group_id'], 'prediction': int(p >= selection['threshold']), 'score_uncalibrated': float(p),
            'project_hazard_rules': rules(r['text']), 'broad_hazard_rules': rules(r['text'], True)} for r, p in zip(rows, scores, strict=True)]})
    print(json.dumps({'status': 'INFERRED_WITHOUT_REFERENCES', 'rows': len(rows)}))


def score():
    selection = validate()
    path = Path('/references/test-references.jsonl')
    if file_hash(path) != selection['test_references_sha256']:
        raise ValueError('Reference holdout changed')
    rows = read_rows(path)
    inference = json.loads((ROOT / 'predictions.json').read_bytes())
    if inference['selection_sha256'] != file_hash(ROOT / 'final-selection.json'):
        raise ValueError('Selection changed since inference')
    lookup = {r['id']: r for r in inference['rows']}
    if set(lookup) != {r['id'] for r in rows} or any(lookup[r['id']]['group_id'] != r['group_id'] for r in rows):
        raise ValueError('Held-out population mismatch')
    result = {'status': 'INCONCLUSIVE', 'reason': 'Only one source-channel-admitted held-out case; no independent sampling CI.',
        'rows': len(rows), 'groups': len({r['group_id'] for r in rows}), 'confidence_interval': None,
        'scores': {system: metrics([r['label'] for r in rows], [lookup[r['id']][system] for r in rows]) for system in ('prediction', 'project_hazard_rules', 'broad_hazard_rules')},
        'selection_sha256': file_hash(ROOT / 'final-selection.json'), 'prediction_sha256': file_hash(ROOT / 'predictions.json'),
        'project_nlp_quality_gate': 'NEEDS_MORE_DATA', 'temporal_gate': 'NEEDS_MORE_DATA', 'release_promoted': False,
        'test_further_tuning_forbidden': True, 'label_name': 'source_native_safety_voice', 'project_label_mapping': None}
    atomic_json(ROOT / 'comparison.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('freeze', 'infer', 'score'))
    args = p.parse_args()
    {'freeze': freeze, 'infer': infer, 'score': score}[args.action]()

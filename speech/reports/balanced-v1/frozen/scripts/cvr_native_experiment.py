"""Real source-native safety-voice classification; never project event gold."""

import argparse
import importlib.metadata
import json
import re
from pathlib import Path

import numpy as np
import skops.io as skops
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.pipeline import FeatureUnion, Pipeline

from north55_speech.core import atomic_json, file_hash, now
from north55_speech.nlp import EventClassifier

C_VALUES = (.25, 1., 4.)
THRESHOLDS = (.35, .5, .65)
HAZARDS = r"\b(?:warning|caution|stall|fire|failure|failed|problem|emergency|danger|unsafe|unstable|too (?:high|low|fast|slow)|can't|cannot|unable|not working|lost|losing|smoke|terrain|pull up|go around)\b"


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def rules(text, broad=False):
    if broad:
        return int(re.search(HAZARDS, text.casefold()) is not None)
    return int(bool(set(EventClassifier().predict(text)['labels']) & {'REPORTED_DEVIATION', 'WARNING_MENTION'}))


def metrics(labels, predicted):
    precision, recall, f1, support = precision_recall_fscore_support(labels, predicted, labels=[0, 1], zero_division=0)
    return {'negative': {'precision': precision[0], 'recall': recall[0], 'f1': f1[0], 'support': int(support[0])},
        'safety_voice': {'precision': precision[1], 'recall': recall[1], 'f1': f1[1], 'support': int(support[1])},
        'macro_f1': float(np.mean(f1)), 'accuracy': float(np.mean(np.asarray(labels) == np.asarray(predicted)))}


def train():
    root = Path('/result')
    if (root / 'selection.json').exists():
        raise ValueError('Frozen selection already exists')
    proof = json.loads(Path('/proof/preparation.json').read_bytes())
    train_rows, dev_rows = [read_rows(Path('/train-dev') / f'{s}.jsonl') for s in ('train', 'dev')]
    if {r['group_id'] for r in train_rows} & {r['group_id'] for r in dev_rows}:
        raise ValueError('Case leakage')
    for split in ('train', 'dev'):
        if file_hash(Path('/train-dev') / f'{split}.jsonl') != proof['files'][f'train-dev/{split}.jsonl']:
            raise ValueError('Prepared train/dev changed')
    root.mkdir(parents=True, exist_ok=True)
    protocol = {'created_at': now().isoformat(), 'c_values': C_VALUES, 'thresholds': THRESHOLDS,
        'maximum_trials': 9, 'selection': 'dev macro F1, then smaller C, then threshold nearest .5',
        'script_sha256': file_hash(Path(__file__)), 'project_rules_sha256': file_hash(Path('/app/src/north55_speech/nlp.py')),
        'preparation_sha256': file_hash(Path('/proof/preparation.json')),
        'features': 'train-only word 1-2 + char_wb 3-5 TF-IDF, min_df2, max_features 30000+50000',
        'test_inputs_sha256': proof['files']['sealed/test-inputs.jsonl'], 'test_references_sha256': proof['files']['sealed/test-references.jsonl'],
        'label': 'source_native_safety_voice', 'project_label_mapping': None, 'release_promoted': False}
    atomic_json(root / 'protocol.json', protocol)
    x_train, y_train = [r['text'] for r in train_rows], [r['label'] for r in train_rows]
    x_dev, y_dev = [r['text'] for r in dev_rows], [r['label'] for r in dev_rows]
    trials, models, probabilities = [], {}, {}
    for c in C_VALUES:
        model = Pipeline([
            ('features', FeatureUnion([
                ('word', TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30000, sublinear_tf=True)),
                ('char', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, max_features=50000, sublinear_tf=True))])),
            ('classifier', LogisticRegression(C=c, class_weight='balanced', max_iter=1000, random_state=55))])
        model.fit(x_train, y_train)
        scores = model.predict_proba(x_dev)[:, 1]
        models[c], probabilities[c] = model, scores
        for threshold in THRESHOLDS:
            trials.append({'C': c, 'threshold': threshold, 'metrics': metrics(y_dev, scores >= threshold)})
    chosen = sorted(trials, key=lambda t: (-t['metrics']['macro_f1'], t['C'], abs(t['threshold'] - .5), t['threshold']))[0]
    model_path = root / 'model.skops'
    skops.dump(models[chosen['C']], model_path)
    unknown = skops.get_untrusted_types(file=model_path)
    if unknown:
        raise ValueError(f'Unexpected serialized estimator types: {unknown}')
    loaded = skops.load(model_path, trusted=[])
    if not np.array_equal(loaded.predict_proba(x_dev), models[chosen['C']].predict_proba(x_dev)):
        raise ValueError('Model reload differs')
    baselines = {name: metrics(y_dev, [rules(text, broad) for text in x_dev]) for name, broad in (('project_hazard_rules', False), ('broad_hazard_rules', True))}
    selection = {'frozen_at': now().isoformat(), 'protocol_sha256': file_hash(root / 'protocol.json'),
        'model_sha256': file_hash(model_path), 'chosen': chosen, 'trials': trials, 'dev_rule_baselines': baselines,
        'train_rows': len(train_rows), 'dev_rows': len(dev_rows), 'train_cases': len({r['group_id'] for r in train_rows}),
        'dev_cases': len({r['group_id'] for r in dev_rows}), 'test_accessed': False, 'label': 'source_native_safety_voice',
        'project_event_gate': 'NEEDS_MORE_DATA', 'release_promoted': False,
        'packages': {p: importlib.metadata.version(p) for p in ('scikit-learn', 'numpy', 'scipy', 'skops')}}
    atomic_json(root / 'dev-predictions.json', [{'id': row['id'], 'group_id': row['group_id'], 'label': row['label'],
        'classifier_score_uncalibrated': float(score), 'prediction': int(score >= chosen['threshold']),
        'project_hazard_rules': rules(row['text']), 'broad_hazard_rules': rules(row['text'], True)} for row, score in zip(dev_rows, probabilities[chosen['C']], strict=True)])
    atomic_json(root / 'selection.json', selection)
    print(json.dumps({'status': 'TRAINED_FROZEN', 'chosen': chosen, 'baselines': baselines, 'train_rows': len(train_rows), 'dev_rows': len(dev_rows)}, indent=2))


def frozen():
    root = Path('/result')
    selection = json.loads((root / 'selection.json').read_bytes())
    protocol = json.loads((root / 'protocol.json').read_bytes())
    if file_hash(root / 'model.skops') != selection['model_sha256'] or file_hash(root / 'protocol.json') != selection['protocol_sha256']:
        raise ValueError('Frozen model/protocol changed')
    if file_hash(Path(__file__)) != protocol['script_sha256'] or file_hash(Path('/app/src/north55_speech/nlp.py')) != protocol['project_rules_sha256']:
        raise ValueError('Frozen code changed')
    return root, selection, protocol


def infer():
    root, selection, protocol = frozen()
    path = Path('/inputs/test-inputs.jsonl')
    if file_hash(path) != protocol['test_inputs_sha256']:
        raise ValueError('Held-out inputs changed')
    if (root / 'test-predictions.json').exists():
        raise ValueError('Held-out inference already exists')
    rows = read_rows(path)
    if any(set(r) != {'id', 'group_id', 'text'} for r in rows):
        raise ValueError('Inference projection includes labels/metadata')
    if skops.get_untrusted_types(file=root / 'model.skops'):
        raise ValueError('Unexpected serialized estimator')
    model = skops.load(root / 'model.skops', trusted=[])
    scores = model.predict_proba([r['text'] for r in rows])[:, 1]
    atomic_json(root / 'test-predictions.json', {'executed_at': now().isoformat(), 'selection_sha256': file_hash(root / 'selection.json'),
        'inputs_sha256': file_hash(path), 'rows': [{'id': r['id'], 'group_id': r['group_id'], 'prediction': int(score >= selection['chosen']['threshold']),
            'classifier_score_uncalibrated': float(score), 'project_hazard_rules': rules(r['text']), 'broad_hazard_rules': rules(r['text'], True)} for r, score in zip(rows, scores, strict=True)]})
    print(json.dumps({'status': 'INFERRED_WITHOUT_REFERENCES', 'rows': len(rows)}))


def score():
    root, selection, protocol = frozen()
    path = Path('/references/test-references.jsonl')
    if file_hash(path) != protocol['test_references_sha256']:
        raise ValueError('Held-out references changed')
    rows = read_rows(path)
    predictions = json.loads((root / 'test-predictions.json').read_bytes())
    if predictions['selection_sha256'] != file_hash(root / 'selection.json'):
        raise ValueError('Selection changed after inference')
    lookup = {r['id']: r for r in predictions['rows']}
    if set(lookup) != {r['id'] for r in rows} or any(lookup[r['id']]['group_id'] != r['group_id'] for r in rows):
        raise ValueError('Held-out population mismatch')
    results = {name: metrics([r['label'] for r in rows], [lookup[r['id']][name] for r in rows]) for name in ('prediction', 'project_hazard_rules', 'broad_hazard_rules')}
    groups = len({r['group_id'] for r in rows})
    report = {'status': 'INCONCLUSIVE', 'reason': 'One scope-admitted held-out case cannot establish generalization; native labels differ from project ontology.',
        'test_rows': len(rows), 'test_cases': groups, 'metrics': results, 'confidence_interval': None,
        'selection_sha256': file_hash(root / 'selection.json'), 'prediction_sha256': file_hash(root / 'test-predictions.json'),
        'project_nlp_quality_gate': 'NEEDS_MORE_DATA', 'temporal_gate': 'NEEDS_MORE_DATA', 'release_promoted': False,
        'limitations': ['Text-only source-native classification, not temporal event detection.',
            'No source labels renamed as project salience or event labels.', 'Only source-channel metadata screening, no independent human scope audit.',
            'Accident transcripts differ from routine simulator speech; some source English is translated.', 'Classifier scores have no probability calibration guarantee.']}
    atomic_json(root / 'test-comparison.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('train', 'infer', 'score'))
    args = parser.parse_args()
    {'train': train, 'infer': infer, 'score': score}[args.action]()

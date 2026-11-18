"""Three additional dev trials using only immediately preceding cabin turns."""

import json
from pathlib import Path

import numpy as np
import skops.io as skops
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from north55_speech.core import atomic_json, file_hash, now
from scripts.cvr_native_experiment import C_VALUES, metrics, read_rows


def contextual_texts(rows):
    output, previous = [], {}
    for row in rows:
        number = int(row['id'].rsplit('-', 1)[1])
        last = previous.get(row['group_id'])
        # No future turn, label, incident details or metadata becomes a feature.
        # Do not bridge an excluded radio/unknown/background turn.
        context = last[1] if last and last[0] == number - 1 else ''
        output.append('CURRENT ' + row['text'] + (' PREVIOUS ' + context if context else ''))
        previous[row['group_id']] = (number, row['text'])
    return output


def main():
    root = Path('/result')
    if (root / 'selection.json').exists():
        raise ValueError('Preserve completed context experiment')
    train, dev = [read_rows(Path('/train-dev') / f'{s}.jsonl') for s in ('train', 'dev')]
    proof = json.loads(Path('/proof/preparation.json').read_bytes())
    for split in ('train', 'dev'):
        if file_hash(Path('/train-dev') / f'{split}.jsonl') != proof['files'][f'train-dev/{split}.jsonl']:
            raise ValueError('Training data changed')
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / 'protocol.json', {'created_at': now().isoformat(), 'script_sha256': file_hash(Path(__file__)),
        'base_experiment_script_sha256': file_hash(Path('/app/scripts/cvr_native_experiment.py')), 'C': C_VALUES, 'threshold': .5,
        'additional_trials': 3, 'cumulative_candidate_trials': 12, 'rule_baselines': 2, 'maximum_total_configurations': 16,
        'context': 'previous admitted turn only when consecutive raw turn number in same case; no future text',
        'test_accessed': False, 'label': 'source_native_safety_voice'})
    x_train, x_dev = contextual_texts(train), contextual_texts(dev)
    y_train, y_dev = [r['label'] for r in train], [r['label'] for r in dev]
    trials, fitted = [], {}
    for c in C_VALUES:
        model = Pipeline([('features', FeatureUnion([
            ('word', TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30000, sublinear_tf=True)),
            ('char', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, max_features=50000, sublinear_tf=True))])),
            ('classifier', LogisticRegression(C=c, class_weight='balanced', max_iter=1000, random_state=55))])
        model.fit(x_train, y_train)
        p = model.predict_proba(x_dev)[:, 1]
        fitted[c] = model, p
        trials.append({'C': c, 'threshold': .5, 'metrics': metrics(y_dev, p >= .5)})
    chosen = sorted(trials, key=lambda t: (-t['metrics']['macro_f1'], t['C']))[0]
    model, predictions = fitted[chosen['C']]
    skops.dump(model, root / 'model.skops')
    if skops.get_untrusted_types(file=root / 'model.skops') or not np.array_equal(skops.load(root / 'model.skops', trusted=[]).predict_proba(x_dev), model.predict_proba(x_dev)):
        raise ValueError('Context model reload failed')
    atomic_json(root / 'dev-predictions.json', [{'id': r['id'], 'group_id': r['group_id'], 'label': r['label'], 'score_uncalibrated': float(p), 'prediction': int(p >= .5)} for r, p in zip(dev, predictions, strict=True)])
    result = {'status': 'TRAINED_DEV_ONLY', 'chosen': chosen, 'trials': trials, 'model_sha256': file_hash(root / 'model.skops'),
        'frozen_at': now().isoformat(), 'protocol_sha256': file_hash(root / 'protocol.json'), 'test_accessed': False, 'release_promoted': False}
    atomic_json(root / 'selection.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

"""Score every frozen ATCOSIM input; never select clips or tune inference."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]/'reports/aviation-v13'
sys.path.insert(0, str(ROOT/'frozen/src'))
from north55_speech.metrics import canonical_normalizer_v1, edit_counts, lexical_normalizer_v1


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def distance(a, b):
    """Independent token edit distance, without jiwer alignment/tie-breaking."""
    a, b = a.split(), b.split()
    previous = list(range(len(b)+1))
    for i, token in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(previous[j]+1, current[-1]+1, previous[j-1]+(token != other)))
        previous = current
    return previous[-1]


def aggregate(rows):
    counts = {k: sum(row[k] for row in rows) for k in ['S', 'D', 'I', 'N', 'H']}
    counts['errors'] = counts['S']+counts['D']+counts['I']
    counts['wer_percent'] = 100*counts['errors']/counts['N']
    counts['clips'] = len(rows)
    return counts


def main():
    plan = read(ROOT/'plan.json')
    assert sha(ROOT/'inputs.json') == plan['input_hashes']['inputs.json']
    assert sha(ROOT/'scoring/references.json') == plan['reference_sha256']
    assert sha(ROOT/'scoring/cached.json') == plan['cached_sha256']
    assert sha(ROOT/'frozen/src/north55_speech/metrics.py') == plan['metric_sha256']
    assert read(ROOT/'parity-verification.json')['status'] == 'PASS'
    protocol = read(ROOT/'scoring-protocol.json')
    assert sha(Path(__file__)) == protocol['script_sha256']
    amendment = read(ROOT/'generation-guard-plan.json')
    assert amendment['original_plan_sha256'] == sha(ROOT/'plan.json')
    assert sha(ROOT/'io-full/consensus.log') == amendment['original_failure_log_sha256']
    for name in ['consensus-guarded', 'consensus-guarded-failure-fixture']:
        verification = read(ROOT/f'io-smoke/{name}-verification.json')
        assert verification['status'] == 'PASS'
        assert verification['artifact_sha256'] == sha(ROOT/f'io-smoke/{name}.json')
    inputs = read(ROOT/'inputs.json')
    ids = {i['id'] for i in inputs}
    assert len(ids) == len(inputs) == plan['count'] == 1901
    refs = read(ROOT/'scoring/references.json')
    assert set(refs) == ids
    hypotheses = read(ROOT/'scoring/cached.json')
    artifacts, records = {}, {}
    for stage in ['hybrid', 'consensus']:
        filename = 'hybrid' if stage == 'hybrid' else 'consensus-guarded'
        path = ROOT/f'io-full/{filename}.json'
        artifact = read(path)
        expected_identity = {'plan': sha(ROOT/'plan.json'), 'driver': plan['driver_sha256'],
                             'runtime': plan['runtime_sha256'][stage],
                             'entrypoint': plan['entrypoint_sha256'][stage], 'smoke': False}
        if stage == 'consensus':
            expected_identity |= {'driver': amendment['guard_driver_sha256'],
                                  'amendment': sha(ROOT/'generation-guard-plan.json'),
                                  'synthetic_failure_fixture': False}
            expected_identity['base'] = sha(ROOT/'io-full/hybrid.json')
            assert artifact['base_file_sha256'] == expected_identity['base']
            assert artifact['candidate'] == 'consensus_v11_generation_fallback_v13' and not artifact['replay_only']
        assert artifact['batch_identity'] == expected_identity
        assert artifact['runtime_sha256'] == plan['runtime_sha256'][stage]
        rows = {Path(r['input_path']).stem: r for r in artifact['records']}
        assert len(rows) == len(artifact['records']) == len(ids) and set(rows) == ids
        for item in inputs:
            row = rows[item['id']]
            assert row['input_sha256'] == item['audio_sha256'] and row['pcm_sha256'] == item['pcm_sha256']
            assert abs(row['duration_sec']-item['duration_sec']) < 1/16000
            checkpoint = read(ROOT/f"io-full/{filename}-records/{item['id']}.json")
            assert checkpoint == {'identity': expected_identity, 'row': row}
            assert isinstance(row['hypothesis'], str)
            if row.get('runtime_failure'):
                assert row['runtime_failure'] == 'canary_generation_limit'
                assert row['rejected_canary']['token_limit_reached'] and row['canary'] is None
                assert row['hypothesis'] == row['base'] and not row['accepted_edits'] and not row['changed']
        hypotheses[stage] = {key: row['hypothesis'] for key, row in rows.items()}
        artifacts[stage], records[stage] = artifact, rows
    assert all(set(rows) == ids for rows in hypotheses.values())
    results, scored = {}, {}
    checks = 0
    for metric, normalizer in [('lexical', lexical_normalizer_v1), ('canonical_numbers', canonical_normalizer_v1)]:
        results[metric], scored[metric] = {}, {}
        for model, texts in hypotheses.items():
            rows = []
            for item in inputs:
                key = item['id']
                reference, hypothesis = normalizer(refs[key]), normalizer(texts[key])
                counts = edit_counts(reference, hypothesis)
                independent = distance(reference, hypothesis)
                assert independent == counts['S']+counts['D']+counts['I'], (metric, model, key)
                checks += 1
                rows.append({'id': key, 'speaker': item['speaker'], **counts, 'errors': independent})
            scored[metric][model] = rows
            results[metric][model] = {
                'overall': aggregate(rows),
                'speakers': {s: aggregate([r for r in rows if r['speaker'] == s]) for s in plan['speakers']},
            }
    paired = {}
    for metric in results:
        before, after = scored[metric]['hybrid'], scored[metric]['consensus']
        paired[metric] = dict(Counter('improved' if b['errors'] < a['errors'] else 'worsened' if b['errors'] > a['errors'] else 'same_error_count'
                                     for a, b in zip(before, after, strict=True)))
    failures = sum(bool(r.get('runtime_failure')) for r in records['consensus'].values())
    assert failures == artifacts['consensus']['generation_failures']
    summary = {'plan_sha256': sha(ROOT/'plan.json'), 'coverage': {'clips': len(inputs),
               'minutes': plan['seconds']/60, 'speakers': len(plan['speakers']), 'omitted_clips': 0},
               'scope': plan['claim'], 'metrics': results, 'v11_guarded_vs_v9_per_clip': paired,
               'routes_v9': dict(Counter(r['reason'] for r in records['hybrid'].values())),
               'v11_guarded_changed_clips': sum(r['changed'] for r in records['consensus'].values()),
               'canary_token_limit_clips': failures,
               'unmodified_v11': {'status': amendment['original_run_status'], 'completed_before_abort': 6,
                                 'failed_id': amendment['original_failed_id'], 'full_corpus_WER': None},
               'consensus_variant': 'v11 with generation-failure fallback to v9',
               'additional_discarded_ASR_calls': amendment['additional_discarded_ASR_calls'],
               'fresh_full_ASR_calls': artifacts['consensus']['actual_ASR_calls'],
               'cached_predictions_reused': plan['historical_predictions']}
    save(ROOT/'scoring/per-clip.json', scored)
    save(ROOT/'comparison.json', summary)
    labels = {'small': 'Whisper small (previous run)', 'atc': 'Whisper medium.en ATC (previous run)',
              'hybrid': 'Cockpit v9 (guarded v10 runtime)', 'consensus': 'v11 + generation-failure fallback to v9'}
    lines = ['# Full ATCOSIM comparison, v13', '',
             f"All **1901 clips / {plan['seconds']/60:.2f} minutes / 4 speakers** were scored. No omitted clips.", '',
             'This is simulated controller speech with publisher transcripts. The published test partition was already used locally as development data; this is not a fresh held-out test. It does not replace cockpit evaluation. No training or threshold changes were made.', '',
             f"**Unmodified v11 failed on clip 7**, after six completed outputs: Canary reached its existing 256-token limit. The fourth row below is a separately declared variant that retains the v9 text on this failure. It encountered **{failures} generation-limit failures out of 1901 clips**; every failed generation is preserved and every clip is scored. Unmodified v11 has no full-corpus WER from the aborted batch. Successful decoding and consensus rules are unchanged. See `generation-guard-plan.json`.", '',
             '| System | Lexical WER | Errors / words | Number-normalized WER |',
             '|---|---:|---:|---:|']
    for model in labels:
        primary = results['lexical'][model]['overall']
        secondary = results['canonical_numbers'][model]['overall']
        lines.append(f"| {labels[model]} | {primary['wer_percent']:.2f}% | {primary['errors']} / {primary['N']} | {secondary['wer_percent']:.2f}% |")
    lines += ['', 'Lower WER is better. Primary WER ignores ordinary punctuation/case; the secondary measure applies the same existing number normalization to references and hypotheses. It is not a correction of the transcripts.', '',
              'The small and ATC predictions were reused from the hash-verified v1 execution (3802 records). Both cockpit profiles were run afresh on all inputs. The frozen checkpoint driver first had to reproduce the previous 16-clip end-to-end outputs; details are in `parity-verification.json`.', '',
              '| Speaker | Clips | Small WER | ATC WER | v9 WER | v11 + fallback WER |', '|---|---:|---:|---:|---:|---:|']
    for speaker in plan['speakers']:
        values = [results['lexical'][m]['speakers'][speaker] for m in labels]
        lines.append(f"| {speaker} | {values[0]['clips']} | "+' | '.join(f"{v['wer_percent']:.2f}%" for v in values)+' |')
    before = results['lexical']['hybrid']['overall']
    after = results['lexical']['consensus']['overall']
    delta = after['errors']-before['errors']
    lines += ['', f"v11 with the failure fallback changes the total lexical error count relative to v9 by **{delta:+d}** ({after['wer_percent']-before['wer_percent']:+.2f} percentage points WER). Per-clip outcomes: `{paired['lexical']}`.", '',
              'The failure handler reproduced all 16 stored successful outputs exactly, and a synthetic limit failure verified retaining the base text while continuing the batch. These replays made no new ASR calls. Six successful outputs from the aborted run were reused; one discarded failing generation was recomputed to capture it. The original aborted log and checkpoints are preserved.', '',
              'These aggregate results cover only four speakers; they do not establish performance across all aviation speech. No automatic profile promotion was performed.', '',
              'Cockpit results remain separate: [16 user-reviewed English clips](../cockpit-reviewed-v12/report.md). The extra [84 clips for manual review](http://localhost:8012/?split=dev) have machine drafts and no new human references from this run. The previous 42-clip queue and 16 reviewed references are preserved.', '',
              f'Validation: {checks} independent token-distance checks; exact coverage and checkpoint identities; frozen metric/runtime/input/reference hashes. See `verification.json` and `comparison.json`.', '']
    (ROOT/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    verification = {'status': 'PASS', 'independent_edit_distance_checks': checks, 'scored_clips_per_system': 1901,
                    'omitted_clips': 0, 'human_labels_created_or_changed': 0, 'sealed_cockpit_test_accessed': False,
                    'scorer_sha256': sha(Path(__file__)), 'plan_sha256': sha(ROOT/'plan.json'),
                    'generation_limit_failures_retained': failures,
                    'outputs': {str(p.relative_to(ROOT)): sha(p) for p in [ROOT/'io-full/hybrid.json', ROOT/'io-full/consensus-guarded.json', ROOT/'comparison.json', ROOT/'report.md']}}
    save(ROOT/'verification.json', verification)
    print(json.dumps({m: results['lexical'][m]['overall'] for m in labels}))


if __name__ == '__main__':
    main()

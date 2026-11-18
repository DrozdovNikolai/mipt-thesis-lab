"""Retain v9 on the frozen v11 generation-limit error; preserve each failure."""
import argparse
import ast
import copy
import hashlib
import sys
import time
from pathlib import Path

import run_checkpointed_asr_v13 as original
from run_checkpointed_asr_v13 import Checkpoints, read, save, sha


class Guard(Checkpoints):
    def __init__(self):
        super().__init__('consensus')
        self.guards = 0

    def visit_Raise(self, node):
        if (isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == 'RuntimeError' and len(node.exc.args) == 1
                and isinstance(node.exc.args[0], ast.Constant)
                and node.exc.args[0].value == 'Canary generation limit reached; preserve the base result for review'):
            self.guards += 1
            return ast.parse('reject_canary(canary)\ncanary = None').body
        return self.generic_visit(node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-smoke', action='store_true')
    parser.add_argument('--inject-limit', action='store_true')
    args = parser.parse_args()
    assert not args.inject_limit or args.replay_smoke
    study, output = Path('/study'), Path('/output')
    plan, amendment = read(study/'plan.json'), read(study/'generation-guard-plan.json')
    assert sha(study/'plan.json') == amendment['original_plan_sha256']
    assert sha(Path(__file__)) == amendment['guard_driver_sha256']
    assert sha(Path(original.__file__)) == plan['driver_sha256']
    source, runtime = Path('/app/scripts/transcribe_cockpit_consensus_v11.py'), Path('/profile/runtime.json')
    assert sha(source) == plan['entrypoint_sha256']['consensus']
    assert sha(runtime) == plan['runtime_sha256']['consensus']
    inputs_name = 'smoke-inputs.json' if args.replay_smoke else 'inputs.json'
    assert sha(study/inputs_name) == plan['input_hashes'][inputs_name]
    inputs = read(study/inputs_name)
    by_file = {r['file']: r for r in inputs}
    assert len(by_file) == len(inputs)
    name = 'consensus-guarded-failure-fixture' if args.inject_limit else 'consensus-guarded'
    destination = output/f'{name}.json'
    identity = {'plan': sha(study/'plan.json'), 'amendment': sha(study/'generation-guard-plan.json'),
                'driver': sha(Path(__file__)), 'runtime': sha(runtime), 'entrypoint': sha(source),
                'smoke': args.replay_smoke, 'synthetic_failure_fixture': args.inject_limit,
                'base': sha(output/'hybrid.json')}
    progress = {'stage': name, 'completed': 0, 'fresh': 0, 'reused': 0, 'failures': 0, 'total': len(inputs)}
    started, pending = time.perf_counter(), []

    def validate(row):
        expected = by_file[Path(row['input_path']).name]
        assert row['input_sha256'] == expected['audio_sha256'] and row['pcm_sha256'] == expected['pcm_sha256']
        assert sha(Path(row['input_path'])) == expected['audio_sha256']

    def store_row(row, fresh):
        validate(row)
        if pending:
            assert len(pending) == 1
            row['rejected_canary'] = pending.pop()
            row['runtime_failure'] = 'canary_generation_limit'
            assert row['hypothesis'] == row['base'] and not row['accepted_edits'] and row['canary'] is None
        path = output/f'{name}-records'/f"{Path(row['input_path']).stem}.json"
        value = {'identity': identity, 'row': row}
        if path.exists():
            assert read(path) == value
        else:
            save(path, value)
        progress['completed'] += 1
        progress['fresh' if fresh else 'reused'] += 1
        progress['failures'] += bool(row.get('runtime_failure'))
        save(output/f'{name}-progress.json', {**progress, 'elapsed_sec': time.perf_counter()-started})
        if progress['completed'] % 50 == 0 or progress['completed'] == len(inputs):
            print(progress, flush=True)

    def checkpoint(row):
        store_row(row, True)

    def restore(input_path):
        key = Path(input_path).stem
        path = output/f'{name}-records'/f'{key}.json'
        if path.exists():
            cached = read(path)
            assert cached['identity'] == identity
        elif not args.replay_smoke and key in amendment['prior_successful_checkpoints']:
            path = output/'consensus-records'/f'{key}.json'
            assert sha(path) == amendment['prior_successful_checkpoints'][key]
            cached = read(path)
            assert cached['identity'] == {k: identity[k] for k in ['plan', 'runtime', 'entrypoint', 'smoke', 'base']} | {'driver': plan['driver_sha256']}
        else:
            return None
        store_row(cached['row'], False)
        return cached['row']

    def reject(result):
        assert result['token_limit_reached'] and not pending
        pending.append(result)

    if destination.exists():
        assert read(destination)['batch_identity'] == identity
        print({'existing_verified': name})
        return
    transformer = Guard()
    tree = ast.fix_missing_locations(transformer.visit(ast.parse(source.read_text(encoding='utf-8'))))
    assert transformer.guards == transformer.append_hooks == transformer.loop_hooks == 1
    sys.path.insert(0, '/app/scripts')
    namespace = {'__name__': 'guarded_frozen_entrypoint', '__file__': str(source),
                 'checkpoint_row': checkpoint, 'restore_row': restore, 'reject_canary': reject}
    exec(compile(tree, str(source), 'exec'), namespace)
    if args.replay_smoke:
        expected = read(output/'consensus.json')['records']
        by_pcm = {r['pcm_sha256']: r for r in expected}
        def replay(model, x):
            pcm = hashlib.sha256(x.astype('<f4').tobytes()).hexdigest()
            result = copy.deepcopy(by_pcm[pcm]['canary'])
            if args.inject_limit and pcm == expected[0]['pcm_sha256']:
                result |= {'token_limit_reached': True, 'eos_reached': False, 'generated_tokens': 256,
                           'hypothesis': 'SYNTHETIC FAILURE FIXTURE, NOT ASR OUTPUT', 'token_ids': [0]*256}
            return result
        namespace['load_canary'] = lambda snapshot: object()
        namespace['transcribe_canary'] = replay
    sys.argv = [str(source), '--base', str(output/'hybrid.json'), '--output', str(destination)]
    namespace['main']()
    result = read(destination)
    assert len(result['records']) == progress['completed'] == len(inputs) and not pending
    result['candidate'] = 'consensus_v11_generation_fallback_v13'
    result['batch_identity'] = identity
    result['actual_ASR_calls'] = {**read(output/'hybrid.json')['actual_ASR_calls'],
                                 'canary': sum(r['canary'] is not None or r.get('rejected_canary') is not None for r in result['records'])}
    result['replay_only'] = args.replay_smoke
    result['new_ASR_calls_this_replay'] = 0 if args.replay_smoke else None
    result['generation_failures'] = progress['failures']
    save(destination, result)
    if args.replay_smoke:
        actual = result['records']
        assert len(actual) == len(expected) == 16
        for index, (before, after) in enumerate(zip(expected, actual, strict=True)):
            if args.inject_limit and index == 0:
                assert after['hypothesis'] == before['base'] and after['runtime_failure'] == 'canary_generation_limit'
                assert after['canary'] is None and not after['accepted_edits'] and not after['changed']
            else:
                assert before == after
        save(output/f'{name}-verification.json', {'status': 'PASS', 'records': 16,
             'identical_success_records': 15 if args.inject_limit else 16, 'synthetic_failure_cases': int(args.inject_limit),
             'new_ASR_calls': 0, 'artifact_sha256': sha(destination)})


if __name__ == '__main__':
    main()

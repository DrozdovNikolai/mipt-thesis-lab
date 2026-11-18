"""Run the frozen local ASR entrypoints with per-record checkpoints and manifest input."""
import argparse
import ast
import hashlib
import json
import sys
import time
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


class Checkpoints(ast.NodeTransformer):
    """Add storage hooks only; ASR, routing and consensus expressions stay unchanged."""
    def __init__(self, stage):
        self.stage = stage
        self.append_hooks = self.loop_hooks = 0

    def visit_Expr(self, node):
        if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == 'append' and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == ('outputs' if self.stage == 'hybrid' else 'results')):
            self.append_hooks += 1
            return [node, ast.parse(f"checkpoint_row({node.value.func.value.id}[-1])").body[0]]
        return self.generic_visit(node)

    def visit_For(self, node):
        self.generic_visit(node)
        if not isinstance(node.target, ast.Name):
            return node
        target = 'input_path' if self.stage == 'hybrid' else 'item'
        if node.target.id == target:
            self.loop_hooks += 1
            key = 'str(input_path)' if self.stage == 'hybrid' else "item['input_path']"
            output = 'outputs' if self.stage == 'hybrid' else 'results'
            prefix = ast.parse(f"cached_row = restore_row({key})\nif cached_row is not None:\n    {output}.append(cached_row)\n    continue").body
            node.body = prefix + node.body
        return node


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['hybrid', 'consensus'])
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    study, output = Path('/study'), Path('/output')
    plan = read(study/'plan.json')
    inputs_name = 'smoke-inputs.json' if args.smoke else 'inputs.json'
    assert sha(study/inputs_name) == plan['input_hashes'][inputs_name]
    inputs = read(study/inputs_name)
    source = Path('/app/scripts')/('transcribe_cockpit_hybrid_v10.py' if args.stage == 'hybrid' else 'transcribe_cockpit_consensus_v11.py')
    runtime = Path('/profile/runtime.json')
    identity = {'plan': sha(study/'plan.json'), 'driver': sha(Path(__file__)),
                'runtime': sha(runtime), 'entrypoint': sha(source), 'smoke': args.smoke}
    assert identity['driver'] == plan['driver_sha256']
    assert identity['runtime'] == plan['runtime_sha256'][args.stage]
    assert identity['entrypoint'] == plan['entrypoint_sha256'][args.stage]
    destination = output/f'{args.stage}.json'
    by_file = {i['file']: i for i in inputs}
    assert len(by_file) == len(inputs)
    if args.stage == 'consensus':
        identity['base'] = sha(output/'hybrid.json')
    started = time.perf_counter()
    progress = {'completed': 0, 'fresh': 0, 'resumed': 0, 'total': len(inputs)}

    def validate(row):
        name = Path(row['input_path']).name
        expected = by_file[name]
        assert row['input_sha256'] == expected['audio_sha256']
        assert row['pcm_sha256'] == expected['pcm_sha256']

    def update(fresh):
        progress['completed'] += 1
        progress['fresh' if fresh else 'resumed'] += 1
        value = {**progress, 'stage': args.stage, 'elapsed_sec': time.perf_counter()-started}
        save(output/f'{args.stage}-progress.json', value)
        if progress['completed'] % 50 == 0 or progress['completed'] == len(inputs):
            print(json.dumps(value), flush=True)

    def checkpoint_row(row):
        validate(row)
        path = output/f'{args.stage}-records'/f"{Path(row['input_path']).stem}.json"
        if path.exists():
            raise ValueError('Unexpected overwrite of checkpoint')
        save(path, {'identity': identity, 'row': row})
        update(True)

    def restore_row(input_path):
        path = output/f'{args.stage}-records'/f'{Path(input_path).stem}.json'
        if not path.exists():
            return None
        cached = read(path)
        assert cached['identity'] == identity
        validate(cached['row'])
        assert sha(Path(input_path)) == by_file[Path(input_path).name]['audio_sha256']
        update(False)
        return cached['row']

    if destination.exists():
        result = read(destination)
        assert result['batch_identity'] == identity
        assert len(result['records']) == len(inputs)
        for row in result['records']:
            validate(row)
        print(json.dumps({'stage': args.stage, 'existing_verified': len(inputs)}), flush=True)
        return
    tree = ast.parse(source.read_text(encoding='utf-8'))
    transformer = Checkpoints(args.stage)
    tree = ast.fix_missing_locations(transformer.visit(tree))
    assert transformer.append_hooks == transformer.loop_hooks == 1
    sys.path.insert(0, '/app/scripts')
    namespace = {'__name__': 'frozen_checkpointed_entrypoint', '__file__': str(source),
                 'checkpoint_row': checkpoint_row, 'restore_row': restore_row}
    exec(compile(tree, str(source), 'exec'), namespace)
    if args.stage == 'hybrid':
        sys.argv = [str(source), *['/input/'+i['file'] for i in inputs], '--language', 'en', '--output', str(destination)]
    else:
        sys.argv = [str(source), '--base', str(output/'hybrid.json'), '--output', str(destination)]
    namespace['main']()
    result = read(destination)
    assert len(result['records']) == progress['completed'] == len(inputs)
    result['batch_identity'] = identity
    result['fresh_ASR_calls_this_attempt'] = result['actual_ASR_calls']
    if args.stage == 'hybrid':
        result['actual_ASR_calls'] = {'whisper': sum(r['whisper'] is not None for r in result['records']),
                                      'parakeet': len(inputs), 'dfn_parakeet': 0}
    else:
        result['actual_ASR_calls'] = {**read(output/'hybrid.json')['actual_ASR_calls'],
                                      'canary': sum(r['canary'] is not None for r in result['records'])}
    save(destination, result)


if __name__ == '__main__':
    main()

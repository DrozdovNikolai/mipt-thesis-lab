"""Download pinned public model assets; this process has no audio mounted."""
import hashlib
import json
import os
from pathlib import Path

import requests
from huggingface_hub import snapshot_download


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    root, output = Path('/models'), Path('/output')
    root.mkdir(exist_ok=True)
    repos = [('nvidia/canary-qwen-2.5b', 'b1469e1bba1cfe140205529c79c434ca47180960',
        ['config.json', 'model.safetensors', 'README.md', 'LICENSES']),
        ('Qwen/Qwen3-1.7B', '70d244cc86ccca08cf5af4e1e306ecf908b1ad5e',
        ['config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json',
            'vocab.json', 'merges.txt', 'README.md', 'LICENSE'])]
    records = []
    for repo, revision, patterns in repos:
        directory = snapshot_download(repo, revision=revision, cache_dir=root/'hf', allow_patterns=patterns)
        folder = Path(directory)
        files = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in folder.iterdir() if p.is_file()}
        records.append({'repo': repo, 'revision': revision, 'snapshot': str(folder), 'files': files})
        print({'downloaded': repo, 'files': len(files)}, flush=True)
    url = 'https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-unknown-linux-musl'
    target = root/'deep-filter'
    if not target.exists():
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with target.with_suffix('.part').open('wb') as stream:
                for chunk in response.iter_content(8*1024*1024):
                    stream.write(chunk)
        target.with_suffix('.part').replace(target)
    target.chmod(0o755)
    binary = {'url': url, 'version': '0.5.6', 'sha256': sha(target), 'bytes': target.stat().st_size}
    manifest = {'models': records, 'deep_filter_binary': binary, 'audio_uploaded': False,
        'source_audio_mounted': False}
    destination = output/'model-manifest.json'
    if destination.exists():
        assert json.loads(destination.read_bytes()) == manifest
    else:
        destination.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    for p in [root, *root.rglob('*')]:
        if not p.is_symlink():
            os.chown(p, 10001, 10001)
    print({'complete': True, 'binary': binary}, flush=True)


if __name__ == '__main__':
    main()

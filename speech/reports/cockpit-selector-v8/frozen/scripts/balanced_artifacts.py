"""Recompute the frozen balanced-sampling scorer from PowerShell or Linux."""

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / 'reports/balanced-v1'


def main():
    script = STUDY / 'scoring/score_balanced_retraining.py'
    expected = json.loads((STUDY / 'scoring/identity.json').read_bytes())['script_sha256']
    if hashlib.sha256(script.read_bytes()).hexdigest() != expected:
        raise ValueError('Frozen scorer changed')
    args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
        '-v', f'{(STUDY / "frozen/src").as_posix()}:/app/src:ro',
        '-v', f'{script.as_posix()}:/app/score_balanced_retraining.py:ro',
        '-v', f'{(STUDY / "evaluation").as_posix()}:/eval',
        '-v', f'{(REPO / "data/curated/language-large-v1/scoring/references.json").as_posix()}:/scoring/references.json:ro',
        'north55-speech-gpu:0.1.0', '/app/score_balanced_retraining.py']
    subprocess.run(args, check=True)


if __name__ == '__main__':
    main()

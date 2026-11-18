"""Freeze code and the selected SOTERIA processing policy before ASR."""
import ast
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/'reports/soteria-v14'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    script=ROOT/'scripts/soteria_v14.py'
    policy=next(ast.literal_eval(n.value) for n in ast.parse(script.read_text()).body
                if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POLICY' for t in n.targets))
    dest=STUDY/'frozen'
    files=list((ROOT/'src/north55_speech').rglob('*.py'))
    files += [ROOT/'scripts'/n for n in ('soteria_v14.py','acquire_soteria_v14.py','freeze_soteria_v14.py','review_dataset.py')]
    files += [p for p in (ROOT/'scripts/annotation_web').iterdir() if p.is_file()]
    files += [ROOT/'tests/test_soteria_v14.py']
    plan={'policy':policy,'script_sha256':sha(script),
          'acquisition_plan_sha256':sha(STUDY/'acquisition-plan.json'),
          'frozen_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in files},
          'new_training_runs':0,'human_labels_created':0,'test_accessed':False}
    path=STUDY/'experiment-plan.json'
    if path.exists():
        if json.loads(path.read_text())!=plan:
            raise ValueError('Preserve frozen experiment')
        for name,value in plan['frozen_sha256'].items():
            if sha(dest/name)!=value:
                raise ValueError('Frozen artifact changed')
    else:
        for p in files:
            target=dest/p.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and sha(target)!=sha(p):
                raise ValueError('Partial frozen code differs')
            shutil.copyfile(p,target)
        path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    for name in ('audio','packet'):
        (ROOT/'data/curated/soteria-v14'/name).mkdir(parents=True,exist_ok=True)
    print(json.dumps({'status':'frozen','files':len(files),'plan_sha256':sha(path)}))


if __name__=='__main__':
    main()

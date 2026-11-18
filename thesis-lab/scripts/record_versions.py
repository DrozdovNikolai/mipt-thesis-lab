import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
result = {}
for p in sorted((root / "worktrees" / "candidate").iterdir()):
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=p).decode().split("\0")
    )
    paths = tracked + subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=p
    ).decode().split("\0")
    result[p.name] = dict(
        commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=p, text=True
        ).strip(),
        files={
            f: hashlib.sha256((p / f).read_bytes()).hexdigest()
            for f in sorted(set(paths))
            if f and not Path(f).name.startswith(".env") and (p / f).is_file()
        },
    )
for dirname in ("benchmarks", "scripts"):
    result[dirname] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root / dirname).rglob("*.py")
    }
Path(sys.argv[1]).write_text(json.dumps(result, indent=2))

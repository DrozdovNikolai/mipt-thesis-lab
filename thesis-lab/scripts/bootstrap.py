"""Freeze current source into experimental worktrees without touching source indexes."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPOS = [
    "firefly-backend",
    "firefly-instructor",
    "firefly-commander",
    "firefly-session",
]
ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


def git(repo, *args):
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Firefly Thesis Lab",
            "-c",
            "user.email=thesis@localhost",
            *args,
        ],
        cwd=repo,
        env=ENV,
    )


def excluded(path):
    p = Path(path)
    return (
        (p.name.startswith(".env") and not p.name.endswith("example"))
        or p.name.startswith("celerybeat-schedule")
        or p.suffix in {".pem", ".p12", ".jks", ".keystore"}
    )


def manifest(repo):
    paths = (
        git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        .decode()
        .split("\0")
    )
    return {
        p: hashlib.sha256((repo / p).read_bytes()).hexdigest()
        for p in sorted(set(paths))
        if p and not excluded(p) and (repo / p).is_file()
    }


def main():
    path = ROOT / "provenance" / "sources.json"
    records = json.loads(path.read_text()) if path.exists() else {}
    for name in REPOS:
        src = ROOT.parent / name
        candidate = ROOT / "worktrees" / "candidate" / name
        baseline = ROOT / "worktrees" / "baseline" / name
        if name in records:
            assert manifest(src) == records[name]["source_sha256"], name
            print(name, "already frozen, source unchanged", flush=True)
            continue
        before = manifest(src)
        status = git(src, "status", "--porcelain=v1", "-z").decode()
        head = git(src, "rev-parse", "HEAD").decode().strip()
        branch = git(src, "branch", "--show-current").decode().strip()
        if not candidate.exists():
            git(
                src,
                "worktree",
                "add",
                "--quiet",
                "-b",
                "thesis/20260916-candidate",
                str(candidate),
                head,
            )
        else:
            assert (
                git(candidate, "branch", "--show-current").decode().strip()
                == "thesis/20260916-candidate"
            )
        changed = set(
            git(src, "diff", "HEAD", "--name-only", "-z").decode().split("\0")
        )
        changed |= set(
            git(src, "ls-files", "--others", "--exclude-standard", "-z")
            .decode()
            .split("\0")
        )
        for p in sorted(changed - {""}):
            if excluded(p):
                continue
            target = candidate / p
            if (src / p).is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / p, target)
            elif not (src / p).exists() and target.is_file():
                target.unlink()
        git(candidate, "add", "-A")
        if git(candidate, "diff", "--cached", "--name-only").strip():
            git(
                candidate,
                "commit",
                "-m",
                "chore(thesis): freeze local source for isolated experiments",
            )
        frozen = git(candidate, "rev-parse", "HEAD").decode().strip()
        git(
            src,
            "worktree",
            "add",
            "--quiet",
            "-b",
            "thesis/20260916-baseline",
            str(baseline),
            frozen,
        )
        if manifest(src) != before:
            raise RuntimeError(f"Source changed concurrently: {name}")
        records[name] = dict(
            original_head=head,
            original_branch=branch,
            frozen_commit=frozen,
            original_status=status,
            source_sha256=before,
            excluded_changed_paths=sorted(p for p in changed if p and excluded(p)),
        )
        (ROOT / "provenance" / "sources.json").write_text(json.dumps(records, indent=2))
        print(name, frozen, "source unchanged", flush=True)


if __name__ == "__main__":
    main()

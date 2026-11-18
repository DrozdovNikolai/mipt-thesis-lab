"""Read-only audit of primary directories and the original worktrees."""

import json
from pathlib import Path
import sys
from scripts.bootstrap import ROOT, REPOS, git, manifest


def main(output):
    before = json.loads(
        (ROOT / "provenance/expanded-main-source-before.json").read_text()
    )
    bases = json.loads((ROOT / "provenance/expanded-sources.json").read_text())
    rows = {}
    for name in REPOS:
        src = ROOT.parent / name
        now = dict(
            head=git(src, "rev-parse", "HEAD").decode().strip(),
            status=git(src, "status", "--porcelain=v1", "-z").decode(),
            source_sha256=manifest(src),
        )
        rows[name] = dict(
            main_head_unchanged=now["head"] == before[name]["head"],
            main_status_unchanged=now["status"] == before[name]["status"],
            main_files_unchanged=now["source_sha256"] == before[name]["source_sha256"],
        )
        candidate = ROOT / "worktrees/candidate" / name
        rows[name]["candidate_head_unchanged"] = (
            git(candidate, "rev-parse", "HEAD").decode().strip()
            == bases[name]["base_commit"]
        )
        rows[name]["candidate_tracked_clean"] = not git(
            candidate, "diff", "HEAD", "--name-only"
        ).strip()
        baseline = ROOT / "worktrees/baseline" / name
        rows[name]["baseline_tracked_clean"] = not git(
            baseline, "diff", "HEAD", "--name-only"
        ).strip()
    passed = all(all(v.values()) for v in rows.values())
    result = dict(passed=passed, records=rows)
    (output / "source-audit.json").write_text(json.dumps(result, indent=2))
    assert passed, result
    print("Primary directories and original worktrees unchanged")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())

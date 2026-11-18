"""Validate and seal one completed expansion; never repairs or changes raw measurements."""

from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from expanded.orchestrate import ROOT, compose, inside, run


def main(root, watch=False, reviewed_metadata_drift=False):
    if watch:
        while not (root / "complete.json").exists():
            if (root / "failure.json").exists():
                raise RuntimeError(
                    "Measurement run failed; preserving partial artifacts"
                )
            time.sleep(5)
    assert (root / "complete.json").exists()
    target = root / "mixed/history-100k"
    inside(target, "scripts.verify_expanded_final", database="projection")
    run([sys.executable, "-m", "expanded.verify", str(root)])
    try:
        run([sys.executable, "-m", "scripts.audit_expanded_sources", str(root)])
    except subprocess.CalledProcessError:
        if not reviewed_metadata_drift:
            raise
        # Preserve the failed strict audit. A recorded review may explain Git
        # metadata drift only; source-content or experimental-worktree drift still fails.
        from scripts.bootstrap import git

        audit = json.loads((root / "source-audit.json").read_text())
        review = json.loads((root / "source-audit-review.json").read_text())
        assert review["decision"] == "finalize_with_metadata_note"
        for name, checks in audit["records"].items():
            assert all(
                value
                for key, value in checks.items()
                if key not in ("main_head_unchanged", "main_status_unchanged")
            ), ("source preservation failed", name, checks)
            repo = ROOT.parent / name
            observed = dict(
                head=git(repo, "rev-parse", "HEAD").decode().strip(),
                status_sha256=hashlib.sha256(
                    git(repo, "status", "--porcelain=v1", "-z")
                ).hexdigest(),
            )
            assert observed == review["observed_metadata"][name], (
                "unreviewed metadata drift",
                name,
            )
        print(
            "Strict Git metadata drift retained; reviewed source contents and worktrees are unchanged",
            flush=True,
        )
    run([sys.executable, "-m", "expanded.report", str(root)])
    backup = root / "database"
    backup.mkdir(exist_ok=True)
    for variant in ("original", "optimized", "projection", "functional"):
        with (backup / (variant + ".dump")).open("wb") as f:
            compose(
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                "thesis",
                "-Fc",
                "thesis_exp_" + variant,
                stdout=f,
            )
    shutil.copyfile(ROOT / "results/expanded-main-launch.log", root / "driver.log")
    shutil.copyfile(ROOT / "EXPANDED_VALIDATION.md", root / "VALIDATION.md")
    # Preserve diagnostic evidence explicitly; a negative pilot is not part of the measured success denominator.
    evidence = root / "boundary-evidence"
    evidence.mkdir(exist_ok=True)
    for p in (ROOT / "results/expanded-browser-pilot3").glob("*states.json"):
        shutil.copyfile(p, evidence / p.name)
    (root / "sealed.json").write_text(
        json.dumps(
            dict(
                sealed_at=datetime.now(UTC).isoformat(),
                strict_source_audit_passed=json.loads(
                    (root / "source-audit.json").read_text()
                )["passed"],
                reviewed_metadata_drift=reviewed_metadata_drift,
            ),
            indent=2,
        )
    )
    hashes = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            hashes.append(
                hashlib.sha256(p.read_bytes()).hexdigest()
                + "  "
                + str(p.relative_to(root))
            )
    (root / "SHA256SUMS").write_text("\n".join(hashes) + "\n")
    compose("stop")
    print("SEALED", root, "files", len(hashes), flush=True)


if __name__ == "__main__":
    main(
        Path(sys.argv[1]).resolve(),
        "--watch" in sys.argv,
        "--reviewed-metadata-drift" in sys.argv,
    )

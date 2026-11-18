"""Execute default data-unavailable outcomes; never manufacture a benchmark or release."""

import json
import subprocess
import sys

from north55_speech.core import atomic_json, settings

entry = [sys.executable, "-c", "from north55_speech.cli import main; main()"]
cases = [
    (["--help"], 0),
    (["doctor"], 0),
    (["acceptance-schema"], 0),
    (["benchmark", "freeze-baseline", "--output", "/reports/baseline.lock.json"], 0),
    (["benchmark", "dev"], 4),
    (["train", "events"], 5),
    (["benchmark", "freeze"], 5),
    (["benchmark", "test"], 5),
]
results = []
for args, expected in cases:
    process = subprocess.run(entry + args, capture_output=True, text=True, timeout=180)
    results.append(
        {
            "arguments": args,
            "exit_code": process.returncode,
            "expected": expected,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    )
    assert process.returncode == expected, results[-1]
report = {"status": "PASS", "executed": True, "cases": results}
atomic_json(settings.report_root / "cli-verification.json", report)
print(
    json.dumps(
        {
            "status": "PASS",
            "cases": len(cases),
            "dev_status": "NEEDS_MORE_DATA",
            "release_promoted": False,
        }
    )
)

"""Must run with docker --network none and prefetched read-only model/audio volumes."""

import json
import os

import psutil

from north55_speech.benchmark import code_hash
from north55_speech.core import atomic_json, settings
from north55_speech.selftest import pipeline_stages

interfaces = sorted(psutil.net_if_addrs())
assert interfaces == ["lo"], f"Network is not isolated: {interfaces}"
assert os.environ.get("HF_HUB_OFFLINE") == "1"
pipeline_stages()
report = json.loads((settings.report_root / "pipeline-stage-smoke.json").read_text())
assert all(not item["result"]["cache_hit"] for item in report["variants"].values())
report.update(
    status="PASS",
    executed=True,
    network_interfaces=interfaces,
    network_mode="none",
    code_hash=code_hash(),
)
atomic_json(settings.report_root / "offline-asr-smoke.json", report)
print(
    json.dumps(
        {
            "status": "PASS",
            "network_interfaces": interfaces,
            "variants": list(report["variants"]),
            "quality_evidence": False,
        }
    )
)

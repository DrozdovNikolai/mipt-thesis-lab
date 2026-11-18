"""Export existing aggregate measurements without copying raw ASR payloads."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = {
    "reports/pending-dev-ablation.json": "runs",
    "reports/additional-sources-v1/asr/comparison.json": "rows",
    "reports/all-sources-v1/evaluation/comparison.json": "rows",
    "reports/clean-control-v1/comparison.json": "rows",
    "reports/language-large-v1/comparison.json": "rows",
    "reports/publisher-weak-v1/comparison.json": "rows",
    "reports/reviewed-pilot-v1/comparison.json": "records",
}


def main() -> None:
    for relative, payload_key in EXPORTS.items():
        source = ROOT / relative
        if not source.is_file():
            print(f"SKIP: local raw report unavailable: {relative}")
            continue
        raw = source.read_bytes()
        original = json.loads(raw)
        if not isinstance(original[payload_key], list):
            raise ValueError(f"Expected a list at {relative}:{payload_key}")
        metrics = {key: value for key, value in original.items() if key != payload_key}
        summary = {
            "source_report": relative,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "omitted_payload_key": payload_key,
            "omitted_record_count": len(original[payload_key]),
            "note": "Aggregate values copied unchanged; no evaluation or gate rerun.",
            "metrics": metrics,
        }
        filename = (
            "pending-dev-ablation-summary.json"
            if source.name == "pending-dev-ablation.json"
            else "metrics-summary.json"
        )
        target = source.with_name(filename)
        target.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode())
        print(f"EXPORTED: {target.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()

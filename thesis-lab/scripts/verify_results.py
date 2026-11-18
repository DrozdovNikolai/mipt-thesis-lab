"""Audit matrix coverage and raw measurement invariants without rerunning experiments."""

import itertools
import json
import math
from pathlib import Path
import sys


def verify(root):
    config = json.loads((root / "run.json").read_text())
    assert (root / "complete.json").exists(), "Run has no completion marker"
    assert not (root / "failure.json").exists(), "Run contains a failure marker"
    counts = {}

    def read(name):
        return [json.loads(s) for s in (root / name).read_text().splitlines() if s]

    def coverage(rows, fields, expected):
        keys = [tuple(r[f] for f in fields) for r in rows]
        assert len(keys) == len(set(keys)), "Duplicate measurement series"
        assert set(keys) == set(expected), "Missing or unexpected matrix cells"

    phase = config["phase"]
    if phase in ("all", "h1"):
        rows = read("h1.jsonl")
        coverage(
            rows,
            ("rep", "cache_bytes", "fault", "variant"),
            itertools.product(
                range(config["h1"]["repeats"]),
                (0, 16384),
                ("clean", "lost_ack_restart", "offline_restart"),
                ("split_full", "split_compact", "unified_compact"),
            ),
        )
        for r in rows:
            assert r["correct_completion"] and r["correct_recovery"]
            assert r["duplicate_events"] == 0
            assert r["comment_count"] == config["h1"]["steps"]
            requests = config["h1"]["steps"] * (
                1 if r["variant"] == "unified_compact" else 2
            ) + (r["fault"] == "lost_ack_restart")
            assert r["requests"] == requests
            assert r["body_bytes"] > 0 and r["delivery_ms"] > 0
        counts["h1_trainings"] = len(rows)

    if phase in ("all", "h2"):
        rows = read("h2.jsonl")
        coverage(
            rows,
            ("rep", "size", "fault", "variant"),
            itertools.product(
                range(config["h2"]["repeats"]),
                config["h2"]["sizes"],
                ("clean", "invalid_second", "interrupted_between", "stale_writer"),
                ("crud_legacy", "crud_versioned", "snapshot"),
            ),
        )
        for r in rows:
            expected_partial = (
                r["fault"] in ("invalid_second", "interrupted_between")
                and r["variant"] != "snapshot"
            )
            expected_lost = (
                r["fault"] == "stale_writer" and r["variant"] == "crud_legacy"
            )
            expected_conflict = (
                r["fault"] == "stale_writer" and r["variant"] != "crud_legacy"
            )
            assert r["partial"] == expected_partial, r
            assert r["lost_update"] == expected_lost, r
            assert r["conflict_detected"] == expected_conflict, r
            assert len(r["statuses"]) == r["requests"]
            if r["fault"] == "clean":
                assert r["correct_expected_state"] and r["actual_durations"] == [7, 9]
        counts["h2_operations"] = len(rows)

    if phase in ("all", "h3"):
        rows = read("h3.jsonl")
        for r in rows:
            r["slice"] = json.dumps(r["filters"], sort_keys=True)
        coverage(
            rows,
            ("rep", "size", "slice", "concurrency", "variant"),
            itertools.product(
                range(config["h3"]["repeats"]),
                config["h3"]["sizes"],
                ("{}", '{"asOfDate": "2020-01-02"}'),
                (1, 8),
                ("baseline", "projection"),
            ),
        )
        expected_requests = config["h3"]["requests"]
        for r in rows:
            assert len(r["latencies_ms"]) == r["requests"] == expected_requests
            assert all(math.isfinite(v) and v > 0 for v in r["latencies_ms"])
            assert math.isclose(r["throughput"], expected_requests / r["seconds"])
            assert r["backend_cpu_seconds"] >= 0
        raw = read("h3-requests.jsonl")
        assert len(raw) == len(rows) * expected_requests
        assert all(r["status"] == 200 for r in raw)
        for r in rows:
            matching = [
                x
                for x in raw
                if all(
                    x[k] == r[k]
                    for k in ("rep", "size", "filters", "concurrency", "variant")
                )
            ]
            assert sorted(x["request"] for x in matching) == list(
                range(expected_requests)
            )
            assert sorted(x["latency_ms"] for x in matching) == sorted(
                r["latencies_ms"]
            )
        checks = read("h3-checks.jsonl")
        assert len(checks) == len(config["h3"]["sizes"]) * 9
        assert all(r["passed"] for r in checks)
        counts.update(
            h3_series=len(rows),
            h3_http_requests=len(raw),
            h3_check_records=len(checks),
            h3_asserted_comparisons=sum(r["count"] for r in checks),
        )

    result = dict(passed=True, counts=counts)
    (root / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve())

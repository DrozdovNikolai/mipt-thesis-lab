"""Check exact coverage, independent rep groups, correctness, and crash evidence."""

import hashlib
import itertools as it
import json
from pathlib import Path
import sys
from expanded.orchestrate import ROOT, PROFILES
from expanded.report import read


def coverage(rows, fields, expected):
    expected = list(expected)
    keys = [tuple(r[f] for f in fields) for r in rows]
    assert len(keys) == len(set(keys)), ("duplicate", fields)
    assert set(keys) == set(expected), (
        "coverage",
        fields,
        len(keys),
        len(set(expected)),
    )


def verify(root):
    assert (root / "complete.json").exists() and not (root / "failure.json").exists()
    reuse = root / "reused-phases.json"
    if reuse.exists():
        for phase, record in json.loads(reuse.read_text()).items():
            for name, expected in record["sha256"].items():
                assert (
                    hashlib.sha256((root / phase / name).read_bytes()).hexdigest()
                    == expected
                ), ("reused phase changed", phase, name)
    counts = {}
    for phase in ("h2", "transport", "browser", "reads", "mixed"):
        assert (root / phase / "complete.json").exists()
        assert not (root / phase / "failure.json").exists()
    h = read(root / "h2/h2-performance.jsonl")
    coverage(
        h,
        ("rep", "size", "edited", "variant"),
        [
            (r, s, e, v)
            for r in range(10)
            for s in (5, 25, 100)
            for e in (2, (s + 1) // 2)
            for v in ("crud", "snapshot", "patch")
        ],
    )
    assert all(
        r["correct"]
        and r["http_ms"] > 0
        and r["bytes"] > 0
        and r["requests"] == (r["edited"] if r["variant"] == "crud" else 1)
        for r in h
    )
    counts["h2_saves"] = len(h)
    c = read(root / "h2/h2-concurrent.jsonl")
    coverage(
        c,
        ("rep", "editors", "overlap", "lease", "variant"),
        it.product(
            range(10),
            (2, 4),
            (False, True),
            ("shared_session", "distinct_sessions"),
            ("crud", "snapshot", "patch"),
        ),
    )
    for r in c:
        assert r["correct"] and r["saved"] == (1 if r["overlap"] else r["editors"])
        assert r["field_conflicts"] == (r["editors"] - 1 if r["overlap"] else 0)
        if r["variant"] != "crud":
            assert r["initial_partial_intents"] == 0
    counts["h2_editor_groups"] = len(c)
    ch = read(root / "h2/h2-checks.jsonl")
    assert len(ch) == 7 and all(r["passed"] for r in ch)
    counts["h2_checks"] = len(ch)
    for request in read(root / "h2/h2-http.jsonl"):
        if request["status"] in (409, 423):
            code = json.loads(request["error"])["error"]["code"]
            assert (
                code
                == {409: "SCENARIO_VERSION_CONFLICT", 423: "SCENARIO_LOCKED"}[
                    request["status"]
                ]
            )
    h = read(root / "transport/h1.jsonl")
    coverage(
        h,
        ("rep", "cache_bytes", "rtt_ms", "kib_s", "gzip", "variant"),
        [
            (r, s, ms, k, g, v)
            for r in range(6)
            for s in (1024, 16384)
            for ms, k in ((0, 0), (80, 512), (250, 64))
            for g in (False, True)
            for v in ("split_full", "split_compact", "unified_compact")
        ],
    )
    wire = read(root / "transport/proxy-http.jsonl")
    requests = read(root / "transport/requests.jsonl")
    for r in h:
        assert (
            r["correct_completion"]
            and r["correct_recovery"]
            and r["duplicate_events"] == 0
            and r["comment_count"] == 6
        )
        assert r["requests"] == (6 if r["variant"] == "unified_compact" else 12)
        own = [x for x in wire if x["label"] == f"transport-{r['training_id']}"]
        assert (
            len(own) == r["requests"]
            and sum(x["request_bytes"] + x["response_bytes"] for x in own)
            == r["wire_bytes"]
        )
        own = [x for x in requests if x["training_id"] == r["training_id"]]
        assert (
            len(own) == r["requests"]
            and sum(x["sent_bytes"] + x["received_bytes"] for x in own)
            == r["body_bytes"]
        )
    counts["h1_protocol_trainings"] = len(h)
    b = read(root / "browser/browser.jsonl")
    for r in b:
        r["network_id"] = r["network"]["id"]
    coverage(
        b,
        ("rep", "network_id", "fault"),
        it.product(range(2), ("lan", "rtt80", "rtt250"), ("offline", "lost_ack")),
    )
    assert all(
        r["correct"]
        and r["processKilled"]
        and r["writerStable"]
        and r["summaryPreserved"]
        and r["receiptAccepted"]
        and r["identicalSubmit"]
        and r["eventCount"] == 4
        and r["submitAttempts"] >= 2
        for r in b
    )
    counts["h1_browser_cases"] = len(b)
    count = 0
    for profile in PROFILES:
        folder = root / "reads" / profile["id"]
        rows = read(folder / "read-series.jsonl")
        http = read(folder / "read-http.jsonl")
        for r in rows:
            r["historical"] = bool(r["filters"])
        coverage(
            rows,
            ("rep", "variant", "historical", "concurrency"),
            it.product(
                range(10),
                ("original", "optimized", "projection"),
                (False, True),
                (1, 8),
            ),
        )
        assert len(http) == 2400 and all(r["ms"] > 0 for r in http)
        assert all(r["correct"] for r in http if r["status"] == 200)
        assert all("transport_error" in r for r in http if r["status"] == 0)
        for variant in ("original", "optimized", "projection"):
            own = [r for r in rows if r["variant"] == variant]
            assert len(set(r["backend_instance"] for r in own)) == 10
            plans = json.loads((folder / f"explain-{variant}.json").read_text())
            assert len(plans) >= 2 and all(r["plan"] for r in plans)
        checks = read(folder / "read-checks.jsonl")
        assert len(checks) == 24 and all(r["passed"] for r in checks)
        for r in rows:
            assert (
                r["requests"] == 20
                and len(r["latencies_ms"]) == r["successful_requests"]
                and r["successful_requests"] + r["errors"] == 20
                and r["seconds"] > 0
            )
            own = [
                x
                for x in http
                if x["rep"] == r["rep"]
                and x["variant"] == r["variant"]
                and x["filters"] == r["filters"]
                and x["concurrency"] == r["concurrency"]
            ]
            assert len(own) == 20
            assert [x["ms"] for x in own if x["correct"]] == r["latencies_ms"]
        count += len(http)
    counts["h3_http_reads"] = count
    counts["h3_http_read_errors"] = sum(
        r["errors"]
        for p in (root / "reads").glob("*/read-series.jsonl")
        for r in read(p)
    )
    folder = root / "mixed/history-100k"
    series = read(folder / "mixed-series.jsonl")
    writes = read(folder / "mixed-writes.jsonl")
    reads = read(folder / "mixed-reads.jsonl")
    coverage(
        series,
        ("rep", "write_rate", "variant", "crash"),
        list(
            it.product(
                range(3), (1, 8), ("original", "optimized", "projection"), (False,)
            )
        )
        + [(0, r, "projection", True) for r in (1, 8)],
    )
    for r in series:
        assert (
            r["writes"] == r["write_rate"] * 30 and r["reads"] == 120 and r["converged"]
        )
        own = [
            x
            for x in writes
            if all(x[k] == r[k] for k in ("rep", "write_rate", "variant", "crash"))
        ]
        assert len(own) == r["writes"] and len({x["pilot_id"] for x in own}) == len(own)
        assert r["write_errors"] == sum(x["status"] != 200 for x in own)
        assert all(x["freshness_ms"] is None or x["freshness_ms"] >= 0 for x in own)
        if r["crash"]:
            assert r["worker_after"]["crashes"] == r["worker_before"]["crashes"] + 1
            assert r["worker_before"]["workerPid"] != r["worker_after"]["workerPid"]
    crashes = read(folder / "worker-crashes.jsonl")
    exits = read(folder / "worker-processes.jsonl")
    assert len(crashes) == 2 and len(exits) == 2
    assert all(x["before_commit"] and x["pending_before"] > 0 for x in crashes)
    assert all(x["exit_code"] == 77 and x["restart_delay_s"] == 5 for x in exits)
    counts.update(
        h3_mixed_cases=len(series),
        h3_mixed_writes=len(writes),
        h3_mixed_reads=len(reads),
        h3_worker_crashes=len(crashes),
    )
    hashes = json.loads((root / "versions.json").read_text())
    changed = []
    checked = 0
    analysis_files = ["expanded/report.py", "expanded/verify.py"]
    for f, h in hashes.items():
        if f in analysis_files:
            continue
        checked += 1
        if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h:
            changed.append(f)
    assert not changed, ("benchmark sources changed during run", changed)
    admission = []
    for p in root.rglob("admission.jsonl"):
        admission += read(p)
    assert admission and any(r["consecutive"] == 3 for r in admission)
    result = dict(
        passed=True,
        counts=counts,
        source_hashes_checked=checked,
        source_manifest_entries=len(hashes),
        analysis_files_excluded=analysis_files,
        admission_samples=len(admission),
    )
    (root / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    verify(Path(sys.argv[1]).resolve())

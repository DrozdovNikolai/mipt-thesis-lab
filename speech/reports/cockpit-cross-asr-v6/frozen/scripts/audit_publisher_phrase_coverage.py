"""Audit coverage and make an explicitly non-training review queue from fixed results."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        assert end > start
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def by_source(samples):
    result = defaultdict(list)
    for sample in samples:
        p = sample["annotation_provenance"]
        result[p["source_sample_id"]].append((p["original_start_sec"], p["original_end_sec"]))
    return {source: union(intervals) for source, intervals in result.items()}


def covered(start, end, intervals):
    return sum(max(0, min(end, b) - max(start, a)) for a, b in intervals)


def total_minutes(grouped):
    return sum(b-a for intervals in grouped.values() for a, b in intervals) / 60


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("/workspace"))
    args = parser.parse_args()
    root = args.workspace
    out = root / "reports/publisher-phrases-v2"
    dataset = root / "data/curated/publisher-phrases-v2"
    previous = root / "data/curated/pair-quality-v1"
    old = rows(root / "data/curated/publisher-recovery-v1/train.jsonl")
    clean_old = [s for s in old if not s["variant_of"]]
    accepted = rows(dataset / "train.jsonl")
    dev = rows(dataset / "dev.jsonl")
    decisions = read(out / "decisions.json")
    plan = read(out / "inference/plan.json")
    execution = read(out / "predictions/execution.json")
    inputs = {i["id"]: i for i in read(out / "scoring/source-plan.json")["items"]}
    old_intervals, new_intervals = by_source(clean_old), by_source(accepted)
    overlap = sum(covered(a, b, old_intervals.get(source, []))
                  for source, intervals in new_intervals.items() for a, b in intervals) / 60
    additive = [s for s in accepted if covered(s["annotation_provenance"]["original_start_sec"],
                    s["annotation_provenance"]["original_end_sec"],
                    old_intervals.get(s["annotation_provenance"]["source_sample_id"], [])) == 0]
    old_windows = [s for s in rows(root / "data/curated/publisher-expanded-v1/all/train.jsonl")
                   if not s["variant_of"]]
    coverage = []
    for s in old_windows:
        p = s["annotation_provenance"]
        seconds = covered(p["original_start_sec"], p["original_end_sec"],
                          new_intervals.get(p["source_sample_id"], []))
        coverage.append({"id": s["sample_id"], "seconds_covered": seconds,
                         "fraction": seconds / s["duration_sec"]})
    document_reasons = {"insufficient_publisher_support", "critical_token_not_supported_by_publisher"}
    review = []
    for d in sorted(decisions, key=lambda d: (-d["publisher"]["coverage"], d["id"])):
        if d["reasons"] and set(d["reasons"]) <= document_reasons:
            item = inputs[d["id"]]
            review.append({**item, "candidate_text": d["target"], "asr_disagreement": d["asr_disagreement"],
                "small_text": read(previous / "small/predictions" / f"{d['id']}.json")["hypothesis"],
                "publisher": d["publisher"], "reasons": d["reasons"],
                "automatic_training_eligible": False, "human_verified": False,
                "review_status": "NEEDS_AUDIO_AND_PUBLISHER_REVIEW"})
    for key, value in execution["predictions"].items():
        assert sha(out / "predictions" / f"{key}.json") == value
    assert len(execution["predictions"]) == len(inputs) == 675
    assert execution["plan_sha256"] == sha(out / "inference/plan.json")
    assert sha(dataset / "dev.jsonl") == plan["dev_sha256"]
    assert sha(root / "data/curated/publisher-recovery-v1/train.jsonl") == plan["old_train_sha256"]
    for sample in accepted:
        prediction = read(out / "predictions" / f"{sample['sample_id']}.json")
        assert sample["reference_text"] == prediction["hypothesis"]
        assert sample["audio_sha256"] == inputs[sample["sample_id"]]["audio_sha256"]
        assert sample["decoded_audio_sha256"]
    for field in ("sample_id", "audio_sha256", "decoded_audio_sha256"):
        assert len({s[field] for s in accepted}) == len(accepted)
    for field in ("session_id", "recording_id", "audio_sha256", "decoded_audio_sha256"):
        assert {s[field] for s in accepted}.isdisjoint(s[field] for s in dev)
    assert {p for s in accepted for p in s["speaker_ids"]}.isdisjoint(p for s in dev for p in s["speaker_ids"])
    assert abs(total_minutes(new_intervals) - sum(s["duration_sec"] for s in accepted)/60) < 0.001
    (dataset / "additional-nonoverlap.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) + "\n" for s in additive), encoding="utf-8")
    write(out / "scoring/review-queue.json", review)
    write(out / "scoring/old-window-coverage.json", coverage)
    result = {"integrity": "PASS", "old_pairs": len(old), "old_minutes": sum(s["duration_sec"] for s in old)/60,
        "old_clean_pairs": len(clean_old), "old_unique_original_minutes": total_minutes(old_intervals),
        "new_pairs": len(accepted), "new_unique_original_minutes": total_minutes(new_intervals),
        "shared_original_minutes": overlap,
        "new_coverage_outside_old_intervals_minutes": total_minutes(new_intervals) - overlap,
        "combined_interval_union_minutes": total_minutes(new_intervals) + total_minutes(old_intervals) - overlap,
        "whole_new_pairs_not_overlapping_old": len(additive),
        "whole_new_nonoverlap_minutes": sum(s["duration_sec"] for s in additive)/60,
        "old_original_train_windows": len(old_windows),
        "old_windows_with_any_new_pair_coverage": sum(v["seconds_covered"] > 0 for v in coverage),
        "old_windows_with_at_least_half_new_pair_coverage": sum(v["fraction"] >= .5 for v in coverage),
        "document_only_rejected_pairs": len(review), "document_only_rejected_minutes": sum(v["duration_sec"] for v in review)/60,
        "document_only_rejected_by_source": dict(Counter(v["source"] for v in review)),
        "rejection_combinations": [{"reasons": list(k), "count": v} for k, v in Counter(tuple(d["reasons"]) for d in decisions).most_common()],
        "dev_byte_identical": True, "raw_medium_targets_unchanged": True, "train_dev_speakers_sessions_recordings_disjoint": True,
        "new_asr_calls_in_audit": 0, "review_queue_used_for_training": False,
        "note": "Additive manifest is a subset of the 96 new pairs. It is not extra to that set. No mixed-policy training or quality measurement was performed."}
    write(out / "coverage-audit.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

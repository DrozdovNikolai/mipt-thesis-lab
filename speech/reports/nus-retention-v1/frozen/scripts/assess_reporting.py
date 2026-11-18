"""Collect current report tests and explicitly attributed prior recovery evidence."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


root = Path("/reports")
folder = root / "reporting-v1"
package = Path("/app")
before = read(folder / "source-before.json")
files = {str(p.relative_to(package)): file_hash(p) for p in sorted((package / "src/north55_speech").rglob("*"))
         if p.is_file() and p.suffix in {".py", ".html", ".js", ".css"}}
files.update({name: file_hash(package / name) for name in ("pyproject.toml", "uv.lock")})
changed = sorted(name for name in before if before[name] != files.get(name))
added = sorted(set(files) - set(before))
atomic_json(folder / "source-after.json", {"files": files, "code_hash": code_hash(), "scorer_hash": scorer_hash()})
baseline = read(Path("/artifacts/reporting-v1/baseline.lock.json"))
atomic_json(folder / "baseline.lock.json", baseline)
previous = read(root / "gate-hardening/verification.json")
cases = list(ET.parse(folder / "all-tests.xml").getroot().iter("testcase"))
tests_ok = bool(cases) and not any(any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases)
cpu = read(folder / "cpu/offline-asr-smoke.json")
gpu = read(folder / "gpu-current/offline-asr-smoke.json")
checks = read(folder / "checks.json")
runtime = read(folder / "runtime.json")
measured = read(folder / "dev-runtime/metrics.json")
rendered = read(folder / "dev-runtime/figures.json")
verified = {
    "expected_source_change_only": set(changed) == {"src/north55_speech/benchmark.py", "src/north55_speech/metrics.py", "pyproject.toml", "uv.lock"}
        and added == ["src/north55_speech/reporting.py"],
    "tests_and_integration_pass": tests_ok and len(cases) == 228 and sum("integration" in c.attrib["classname"] for c in cases) == 9,
    "static_dependencies_compose": all(v["exit_code"] == 0 for v in checks.values()),
    "locked_dependency_versions_unchanged": read(folder / "dependency-diff.json") == {"changed": {}, "added": {}},
    "baseline_unchanged_new_code_frozen": baseline["code_hash"] == code_hash() and baseline["scorer_hash"] == scorer_hash()
        and baseline["config"] == read(root / "gate-hardening/baseline.lock.json")["config"],
    "current_cpu_gpu_offline": all(r["status"] == "PASS" and r["code_hash"] == code_hash() and r["network_interfaces"] == ["lo"]
        and all(not x["result"]["cache_hit"] and x["result"]["segments"] for x in r["variants"].values()) for r in (cpu, gpu)),
    "running_api_worker_current": all(runtime["containers"][name] == runtime["images"]["north55-speech:0.1.0"] for name in ("north55-speech-api-1", "north55-speech-worker-1")),
    "prior_recovery_evidence_preserved": previous["verification"] == "PASS"
        and previous["checks"]["broker_outage_and_worker_sigkill_recovered"]
        and all(before[f"src/north55_speech/{name}"] == files[f"src/north55_speech/{name}"] for name in ("jobs.py", "db.py", "api.py", "core.py")),
    "annotation_preserved": read(folder / "annotation-service.json")["status"] == "PASS"
        and read(folder / "annotation-service.json")["annotation_writes"] == 0
        and runtime["human_revision_files"] == [],
    "all_64_historical_runs_retained": measured["runs"] == 64 and sum(t["runs"] for t in measured["runtime_trials"]) == 64,
    "only_runtime_plotted_without_gold": [f["name"] for f in rendered if f["status"] == "MEASURED"] == ["dev-runtime"]
        and measured["baseline_wer"] is None and measured["candidate_wer"] is None and measured["quality_evidence"] is False,
    "no_final_test_access": not (root / "test_access_log.jsonl").exists(),
}
status = "PASS" if all(verified.values()) else "FAIL"
engineering = {"status": status, "code_hash": code_hash(), "scorer_hash": scorer_hash(),
               "test_cases": len(cases), "integration_cases": 9,
               "reasons": [key for key, value in verified.items() if not value],
               "evidence_directory": "reporting-v1", "prior_recovery_evidence": "gate-hardening/verification.json"}
report = {"created_at": now(), "status": status, "checks": verified, "changed_existing_files": changed, "added_core_files": added,
          "code_hash": code_hash(), "scorer_hash": scorer_hash(), "tests_passed": len(cases),
          "engineering_gate": engineering, "asr_quality_gate": previous["asr_quality_gate"],
          "nlp_quality_gate": previous["nlp_quality_gate"], "temporal_event_gate": previous["temporal_event_gate"],
          "candidate_selected": False, "release_promoted": False, "validated_scope": [],
          "research_objective_achieved": False,
          "review_needed": "18 clips / 6 minutes; zero human revisions at this verification",
          "browser_check": "Report header and runtime figure visually inspected; temporary local preview stopped",
          "recovery_check": "Prior executed broker outage/worker SIGKILL evidence reused: recovery source bytes and locked dependency versions unchanged",
          "gpu_check": "gpu-current is the new-image smoke; gpu is an earlier smoke before the image update and is not counted",
          "build_note": "CPU full Dockerfile build; active optional runtimes updated from verified prior images with uv sync --frozen. A redundant GPU BuildKit build completed after its parent CLI stopped; redundant fresh training build cancelled. Active image identities are in runtime.json.",
          "evidence_sha256": {str(p.relative_to(root)): file_hash(p) for p in [folder / "all-tests.xml", folder / "checks.json",
              folder / "runtime.json", folder / "source-after.json", folder / "source-before.json", folder / "baseline.lock.json",
              folder / "cpu/offline-asr-smoke.json", folder / "gpu-current/offline-asr-smoke.json", folder / "dev-runtime/metrics.json",
              root / "gate-hardening/verification.json"]}}
atomic_json(folder / "verification.json", report)
if status == "PASS":
    atomic_json(root / "engineering-gate.json", engineering)
print(json.dumps({"status": status, "checks": verified, "research": "NEEDS_MORE_DATA"}))
if status != "PASS":
    raise SystemExit(1)

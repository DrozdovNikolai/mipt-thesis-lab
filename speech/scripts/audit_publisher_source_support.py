"""Hold ASR text fixed to measure only the effect of publisher text repair."""

import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from scripts.expand_publisher_pairs import FAMILIES
from scripts.publisher_phrase_support import POLICY, support


def read(path):
    return json.loads(path.read_bytes())


def main():
    workspace, out = Path("/workspace"), Path("/output")
    base = workspace / "data/curated/pair-quality-v1"
    old = read(base / "documents.json")
    new = read(out / "scoring/documents.json")
    plan = read(base / "plan.json")
    texts = {}
    for name in old:
        texts[name] = {"before": "\n".join(b["text"] for b in old[name]["blocks"]),
                       "after": "\n".join(line["text"] for line in new[name]["lines"]
                                          if not line.get("excluded_layout", False))}
    decisions = []
    for index, item in enumerate(plan["items"]):
        hyp = read(base / "small/predictions" / f"{item['id']}.json")["hypothesis"]
        versions = {}
        for version in ("before", "after"):
            best = max((support(hyp, texts[name+".json"][version]) for name in FAMILIES[item["family"]]),
                       key=lambda p: (p["coverage"], p["critical_supported"]))
            versions[version] = {"coverage": best["coverage"], "critical_supported": best["critical_supported"],
                                 "supported": best["coverage"] >= POLICY["minimum_publisher_coverage"] and best["critical_supported"]}
        decisions.append({"id": item["id"], **versions})
        if (index+1) % 100 == 0:
            print(json.dumps({"source_audited": index+1}), flush=True)
    summary = {"same_asr_inputs": len(decisions), "new_asr_calls": 0,
               "before_supported": sum(d["before"]["supported"] for d in decisions),
               "after_supported": sum(d["after"]["supported"] for d in decisions),
               "newly_supported": sum(d["after"]["supported"] and not d["before"]["supported"] for d in decisions),
               "lost_support": sum(d["before"]["supported"] and not d["after"]["supported"] for d in decisions),
               "interpretation": "Publisher support of fixed machine text only; neither audio truth nor final pair acceptance",
               "new_documents_sha256": file_hash(out / "scoring/documents.json")}
    atomic_json(out / "source-support-audit.json", summary)
    atomic_json(out / "scoring/source-support-rows.json", decisions)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

"""Source-text support for weak ASR pairs; never changes evaluation normalizers."""

import difflib
import math
import statistics

from north55_speech.metrics import edit_counts, lexical_normalizer_v1
from scripts.publisher_alignment import number_tokens

EXPANSIONS = {
    "rwy": "runway", "gnd": "ground", "qty": "quantity", "ldg": "landing",
    "hyd": "hydraulic", "eng": "engine", "std": "standard", "clsd": "closed",
    "lckd": "locked", "brk": "brake", "splrs": "spoilers", "batt": "battery",
}
COMPOUNDS = {"check list": "checklist", "anti ice": "antiice", "auto brake": "autobrake",
             "take off": "takeoff", "de ice": "deice"}
ACRONYMS = {"apu", "adirs", "ecam", "irs", "fmc", "mcp", "fcu", "pcl", "rpm", "itt",
            "ng", "trq", "eis", "cas", "lfe", "qnh", "gpws", "fcs", "tcas"}
STATES = {"no", "not", "never", "without", "cannot", "unable", "negative", "on", "off",
          "up", "down", "left", "right", "open", "closed", "arm", "armed", "disarm", "disarmed"}
POLICY = {"version": "publisher_phrase_consensus_v2", "minimum_words": 2,
          "maximum_asr_disagreement": 0.15, "exact_asr_below_words": 8,
          "minimum_publisher_coverage": 0.9, "minimum_median_word_probability": 0.6,
          "maximum_zero_duration_fraction": 0.25, "maximum_source_span_ratio": 3.0,
          "human_verified": False, "training_steps": 0}


def search_normalize(text):
    text = lexical_normalizer_v1(text)
    for first, second in COMPOUNDS.items():
        text = text.replace(first, second)
    for acronym in sorted(ACRONYMS, key=lambda s: (-len(s), s)):
        text = (" " + text + " ").replace(" " + " ".join(acronym) + " ", " " + acronym + " ").strip()
    return " ".join(EXPANSIONS.get(w, w) for w in text.split())


def critical(text):
    return [w for w in search_normalize(text).split() if w in STATES or w.endswith("n't")]


def support(text, script):
    spoken, printed = search_normalize(text).split(), search_normalize(script).split()
    if not spoken or not printed:
        return {"coverage": 0.0, "critical_supported": False, "span": [0, 0]}
    width = max(30, int(len(spoken) * POLICY["maximum_source_span_ratio"]))
    important = {i for i, w in enumerate(spoken) if w in STATES or w.endswith("n't") or number_tokens(w)}
    best = None
    for offset in range(0, len(printed), max(1, len(spoken) // 2)):
        matches = difflib.SequenceMatcher(None, spoken, printed[offset:offset + width], autojunk=False).get_matching_blocks()
        matches = [m for m in matches if m.size]
        if not matches:
            continue
        hit = {k for m in matches for k in range(m.a, m.a + m.size)}
        a, b = matches[0].b, matches[-1].b + matches[-1].size
        if b - a > POLICY["maximum_source_span_ratio"] * len(spoken):
            continue
        if len(spoken) < POLICY["exact_asr_below_words"] and (b - a != len(spoken) or len(hit) != len(spoken)):
            continue
        candidate = {"coverage": len(hit) / len(spoken), "critical_supported": important <= hit,
                     "span": [offset + a, offset + b], "matched_word_indices": sorted(hit),
                     "printed_span": " ".join(printed[offset + a:offset + b])}
        rank = (candidate["coverage"], candidate["critical_supported"], -(b - a))
        if best is None or rank > best[0]:
            best = rank, candidate
    return best[1] if best else {"coverage": 0.0, "critical_supported": False, "span": [0, 0]}


def assess(small, medium, documents, duration):
    if small.get("error") or medium.get("error"):
        return {"accepted": False, "reasons": ["asr_failure"]}
    target = medium["hypothesis"].strip()
    reasons = []
    left, right = search_normalize(target), search_normalize(small["hypothesis"])
    counts = edit_counts(left, right)
    n = counts["N"]
    disagreement = (counts["S"] + counts["D"] + counts["I"]) / max(1, n)
    if n < POLICY["minimum_words"]:
        reasons.append("too_short")
    if disagreement > (0 if n < POLICY["exact_asr_below_words"] else POLICY["maximum_asr_disagreement"]):
        reasons.append("asr_disagreement")
    if number_tokens(target) != number_tokens(small["hypothesis"]):
        reasons.append("numeric_disagreement")
    if critical(target) != critical(small["hypothesis"]):
        reasons.append("state_or_negation_disagreement")
    supported = []
    for name, doc in documents.items():
        script = "\n".join(line["text"] for line in doc["lines"] if not line.get("excluded_layout", False))
        supported.append({"document": name, **support(target, script)})
    best = max(supported, key=lambda p: (p["coverage"], p["critical_supported"]))
    if best["coverage"] < POLICY["minimum_publisher_coverage"]:
        reasons.append("insufficient_publisher_support")
    if not best["critical_supported"]:
        reasons.append("critical_token_not_supported_by_publisher")
    for name, words in (("small", small["words"]),
                        ("medium", [w for s in medium["segments"] for w in s["words"]])):
        probabilities = [w.get("probability") for w in words]
        if not probabilities or any(p is None or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities):
            reasons.append(name + "_invalid_probability")
        elif statistics.median(probabilities) < POLICY["minimum_median_word_probability"]:
            reasons.append(name + "_low_score")
        times = [(w.get("start_sec", w.get("start")), w.get("end_sec", w.get("end"))) for w in words]
        if not times or any(a is None or b is None or not math.isfinite(a) or not math.isfinite(b)
                            or not 0 <= a <= b <= duration + 0.05 for a, b in times):
            reasons.append(name + "_invalid_timeline")
        elif sum(a == b for a, b in times) / len(times) > POLICY["maximum_zero_duration_fraction"]:
            reasons.append(name + "_collapsed_times")
    return {"accepted": not reasons, "reasons": reasons, "target": target,
            "asr_disagreement": disagreement, "publisher": best,
            "target_origin": "unprompted_medium_en_prediction", "human_verified": False}

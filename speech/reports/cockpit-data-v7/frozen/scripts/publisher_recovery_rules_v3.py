"""Traceable token spans, typed publisher slots and fresh audio rechecks."""

import difflib
import math
import re
import statistics

from north55_speech.metrics import edit_counts, lexical_normalizer_v1
from scripts.audit_bleriot_remaining import ALIASES
from scripts.publisher_alignment import number_tokens
from scripts.publisher_phrase_support import ACRONYMS, COMPOUNDS, EXPANSIONS, STATES, support

POLICY = {"version": "publisher_template_recovery_v3", "minimum_literal_words": 4,
    "minimum_seconds": 1.2, "maximum_seconds": 25, "maximum_boundary_disagreement_sec": .45,
    "padding_sec": .15, "median_word_probability": .6, "maximum_zero_duration_fraction": .25,
    "fresh_medium_exact": True, "large_disagreement": .1, "short_exact_below_words": 8,
    "numeric_and_state_agreement": "exact", "human_verified": False, "training_steps": 0}
NUMBER = r"(?:\d+(?:[.,]\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|point)(?: (?:\d+(?:[.,]\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|point)){0,11}"
RULES = {**COMPOUNDS, **EXPANSIONS, **ALIASES, "&": "and"}
RULES.update({" ".join(a): a for a in ACRONYMS})


def mapped_tokens(words):
    tokens = [{"text": token, "a": i, "b": i+1} for i, word in enumerate(words)
              for token in lexical_normalizer_v1(word["word"]).split()]
    # Preserve originating word intervals through multi-token abbreviations.
    for key, value in sorted(RULES.items(), key=lambda p: (-len(p[0].split()), p[0])):
        pattern, replacement = key.split(), value.split()
        result, i = [], 0
        while i < len(tokens):
            if [t["text"] for t in tokens[i:i+len(pattern)]] == pattern:
                result.extend({"text": v, "a": tokens[i]["a"], "b": tokens[i+len(pattern)-1]["b"]} for v in replacement)
                i += len(pattern)
            else:
                result.append(tokens[i])
                i += 1
        tokens = result
    return tokens


def normalize(text):
    return " ".join(t["text"] for t in mapped_tokens([{"word": w} for w in text.split()]))


def word_list(prediction):
    raw = prediction.get("words")
    if raw is None:
        raw = [w for s in prediction.get("segments", []) for w in s["words"]]
    return [{**w, "start_sec": w.get("start_sec", w.get("start")),
             "end_sec": w.get("end_sec", w.get("end"))} for w in raw]


def words_ok(words, duration):
    if not words:
        return False
    if any(w.get("probability") is None or not math.isfinite(w["probability"])
           or not 0 <= w["probability"] <= 1 for w in words):
        return False
    if any(w["start_sec"] is None or w["end_sec"] is None
           or not math.isfinite(w["start_sec"]) or not math.isfinite(w["end_sec"])
           or not 0 <= w["start_sec"] <= w["end_sec"] <= duration+.05 for w in words):
        return False
    return (statistics.median(w["probability"] for w in words) >= POLICY["median_word_probability"]
            and sum(w["start_sec"] == w["end_sec"] for w in words)/len(words)
            <= POLICY["maximum_zero_duration_fraction"])


def states(text):
    return [w for w in normalize(text).split() if w in STATES or w.endswith("n't")]


def compatible_text(target, other, exact=False):
    a, b = normalize(target), normalize(other)
    c = edit_counts(a, b)
    limit = 0 if exact or c["N"] < POLICY["short_exact_below_words"] else POLICY["large_disagreement"]
    return ((c["S"] + c["D"] + c["I"])/max(1, c["N"]) <= limit
            and number_tokens(target) == number_tokens(other) and states(target) == states(other))


def fresh_reasons(candidate, medium, large, duration):
    reasons = []
    for name, prediction in (("medium", medium), ("large", large)):
        if prediction.get("error"):
            reasons.append(name+"_asr_error")
            continue
        if not compatible_text(candidate["target"], prediction["hypothesis"], exact=name == "medium"):
            reasons.append(name+"_text_or_critical_disagreement")
        if not words_ok(word_list(prediction), duration):
            reasons.append(name+"_word_quality")
    return reasons


def crop_candidate(mt, st, mw, sw, ma, mb, sa, sb, duration, evidence):
    # Never split the spelling of one ASR word through an expanded search token.
    for tokens, a, b in ((mt, ma, mb), (st, sa, sb)):
        if a and tokens[a-1]["b"] > tokens[a]["a"]:
            return None
        if b < len(tokens) and tokens[b-1]["b"] > tokens[b]["a"]:
            return None
    wa, wb, xa, xb = mt[ma]["a"], mt[mb-1]["b"], st[sa]["a"], st[sb-1]["b"]
    m, s = mw[wa:wb], sw[xa:xb]
    target = "".join(w["word"] for w in m).strip()
    other = "".join(w["word"] for w in s).strip()
    if not compatible_text(target, other, exact=True) or not words_ok(m, duration) or not words_ok(s, duration):
        return None
    if any(w["start_sec"] == w["end_sec"] for w in (m[0], m[-1], s[0], s[-1])):
        return None
    # Adjacent omitted negations and partial number sequences require a larger span.
    for words, a, b in ((mw, wa, wb), (sw, xa, xb)):
        if a and (states(words[a-1]["word"]) in (["not"], ["no"], ["never"])
                  or (number_tokens(words[a-1]["word"]) and number_tokens(words[a]["word"]))):
            return None
        if b < len(words) and number_tokens(words[b-1]["word"]) and number_tokens(words[b]["word"]):
            return None
    delta = max(abs(m[0]["start_sec"]-s[0]["start_sec"]), abs(m[-1]["end_sec"]-s[-1]["end_sec"]))
    if delta > POLICY["maximum_boundary_disagreement_sec"]:
        return None
    start = max(0, min(m[0]["start_sec"], s[0]["start_sec"])-POLICY["padding_sec"])
    end = min(duration, max(m[-1]["end_sec"], s[-1]["end_sec"])+POLICY["padding_sec"])
    if not POLICY["minimum_seconds"] <= end-start <= POLICY["maximum_seconds"]:
        return None
    return {"kind": "subphrase", "start_sec": start, "end_sec": end, "target": target,
        "small_target": other, "medium_word_range": [wa, wb], "small_word_range": [xa, xb],
        "boundary_disagreement_sec": delta, "publisher": evidence}


def propose_subphrases(small, medium, documents, slots, duration):
    mw, sw = word_list(medium), word_list(small)
    mt, st = mapped_tokens(mw), mapped_tokens(sw)
    a, b = [t["text"] for t in mt], [t["text"] for t in st]
    proposals = []
    for common in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        if common.size < 3:
            continue
        phrase_tokens = a[common.a:common.a+common.size]
        text = " ".join(phrase_tokens)
        for name, body in documents.items():
            printed = normalize(body).split()
            for match in difflib.SequenceMatcher(None, phrase_tokens, printed, autojunk=False).get_matching_blocks():
                if match.size < POLICY["minimum_literal_words"]:
                    continue
                evidence = {"document": name, "mode": "literal", "start_token": match.b,
                            "end_token": match.b+match.size, "text": " ".join(printed[match.b:match.b+match.size])}
                proposal = crop_candidate(mt, st, mw, sw, common.a+match.a, common.a+match.a+match.size,
                    common.b+match.a, common.b+match.a+match.size, duration, evidence)
                if proposal:
                    proposals.append(proposal)
        if slots["document"] not in documents:
            continue
        forms = [{**s, "mode": "numeric_slot"} for s in slots["slots"]]
        forms += [{**s, "mode": "repeated_response"} for s in slots.get("fixed_repeats", [])]
        forms += [{"id": "heading_"+str(i), "source_line": line, "mode": "spoken_heading",
                   "pattern": re.escape(normalize(line))+r" checklist(?: completed)?"}
                  for i, line in enumerate(slots.get("spoken_heading_forms", []))]
        for slot in forms:
            pattern = r"(?<!\S)" + slot["pattern"].replace("{NUMBER}", NUMBER) + r"(?!\S)"
            for match in re.finditer(pattern, text):
                left = len(text[:match.start()].split())
                length = len(match.group().split())
                value = match.groupdict().get("value", "")
                if slot["mode"] == "numeric_slot" and not number_tokens(value):
                    continue
                # Only the printed field permits these audio-supplied numbers.
                printed = normalize(documents[slots["document"]])
                anchor = normalize(slot["source_line"])
                position = printed.find(anchor)
                if position < 0:
                    raise ValueError("Pinned template line is absent from the publisher document")
                evidence = {"document": slots["document"], "mode": slot["mode"], "slot_id": slot["id"],
                    "source_line": slot["source_line"], "start_token": len(printed[:position].split()),
                    "slot_surface": value, "slot_numbers": number_tokens(value),
                    "value_from_audio": True, "document_confirms_value": False}
                proposal = crop_candidate(mt, st, mw, sw, common.a+left, common.a+left+length,
                    common.b+left, common.b+left+length, duration, evidence)
                if proposal:
                    proposals.append(proposal)
    unique = {}
    for p in sorted(proposals, key=lambda p: (p["publisher"]["mode"] != "numeric_slot", p["publisher"]["start_token"])):
        unique.setdefault((p["start_sec"], p["end_sec"], p["target"]), p)
    return list(unique.values())


def whole_support(target, documents):
    return max(({"document": name, **support(normalize(target), normalize(body))} for name, body in documents.items()),
               key=lambda p: (p["coverage"], p["critical_supported"]))


def ordered_nonoverlap(candidates):
    """Maximum-duration chain with nondecreasing publisher positions inside a parent clip."""
    ordered = sorted(candidates, key=lambda p: (p["end_sec"], p["start_sec"], p["target"]))
    chains = []
    for i, current in enumerate(ordered):
        duration = current["end_sec"]-current["start_sec"]
        best = (duration, [current])
        for j in range(i):
            previous = ordered[j]
            pc, pp = current["publisher"], previous["publisher"]
            in_order = pc["document"] != pp["document"] or pc.get("start_token", 0) >= pp.get("start_token", 0)
            if previous["end_sec"] <= current["start_sec"] and in_order:
                score = chains[j][0]+duration
                if score > best[0]:
                    best = score, chains[j][1]+[current]
        chains.append(best)
    return max(chains, key=lambda c: c[0])[1] if chains else []

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from north55_speech.schemas import Entity, Event, PipelineConfig, Segment

EN_ONES = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(20),
        strict=True,
    )
)
EN_TENS = dict(
    zip(
        "twenty thirty forty fifty sixty seventy eighty ninety".split(),
        range(20, 100, 10),
        strict=True,
    )
)
RU = {
    "ноль": 0,
    "нуль": 0,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}
NUMBERS = EN_ONES | EN_TENS | RU
NUMBERS.update(
    {
        "одного": 1,
        "одной": 1,
        "двух": 2,
        "трех": 3,
        "трёх": 3,
        "четырех": 4,
        "четырёх": 4,
        "пяти": 5,
        "шести": 6,
        "семи": 7,
        "восьми": 8,
        "девяти": 9,
        "десяти": 10,
        "пятнадцати": 15,
        "шестнадцати": 16,
        "двадцати": 20,
        "тридцати": 30,
        "сорока": 40,
        "пятидесяти": 50,
        "шестидесяти": 60,
        "семидесяти": 70,
        "восьмидесяти": 80,
        "девяноста": 90,
    }
)
SCALES = {"hundred": 100, "thousand": 1000, "тысяча": 1000, "тысячи": 1000, "тысяч": 1000}


def parse_number(surface: str) -> tuple[int | float | None, list[Any]]:
    text = surface.casefold().strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        value = float(text.replace(",", "."))
        return int(value) if value.is_integer() else value, []
    words = text.replace("-", " ").split()
    if not words or any(w not in NUMBERS and w not in SCALES for w in words):
        return None, []
    values = [NUMBERS.get(w) for w in words]
    if all(v is not None and v < 10 for v in values):
        return int("".join(str(v) for v in values)), []
    if (
        len(values) == 2
        and values[0] is not None
        and values[1] is not None
        and values[0] < 10
        and values[1] >= 20
    ):
        # "one sixty" convention is ambiguous without unit/context; preserve alternatives.
        return None, [values[0] * 100 + values[1], sum(values)]
    total = current = 0
    previous = 100000
    for word in words:
        if word in SCALES:
            scale = SCALES[word]
            if scale == 100:
                current = max(current, 1) * scale
            else:
                total += max(current, 1) * scale
                current = 0
            previous = scale
        else:
            value = NUMBERS[word]
            if value >= previous:
                return None, []
            current += value
            previous = value
    return total + current, []


class TextNormalizer:
    version = "display_normalizer_v1"

    def normalize(self, segment: Segment) -> Segment:
        old = segment.raw_asr_text
        new = re.sub(r"\s+", " ", unicodedata.normalize("NFC", old)).strip()
        segment.display_text = new
        if new != old:
            segment.normalization_changes = [
                {
                    "old": old,
                    "new": new,
                    "rule_id": "nfc_whitespace",
                    "source_span": [0, len(old)],
                    "justification": "Unicode NFC and whitespace formatting only",
                    "version": self.version,
                }
            ]
        return segment


class EntityExtractor:
    version = "speech_entities_v1"
    numeric_cues = {
        "flaps_setting": r"\b(?:flaps?|закрылк\w*)\b",
        "speed_mention": r"\b(?:speed|скорост\w*)\b",
        "altitude_mention": r"\b(?:altitude|высот\w*)\b",
        "heading_mention": r"\b(?:heading|курс\w*)\b",
    }

    def extract(self, segment: Segment) -> list[Entity]:
        raw = segment.raw_asr_text
        # One output codepoint per original codepoint keeps source_span exact even for ß/İ.
        text = "".join(char.casefold() if len(char.casefold()) == 1 else char for char in raw)
        result: list[Entity] = []

        def add(
            kind: str,
            start: int,
            end: int,
            value: Any,
            unit: str | None = None,
            alternatives: list | None = None,
        ):
            # Raw codepoint spans are never based on transformed display text.
            context = text[max(0, start - 35) : end]
            polarity: Literal["affirmative", "negated", "uncertain"] = (
                "negated"
                if re.search(r"\b(?:not|no|never|не|нет)\b|n't\b", context)
                else "affirmative"
            )
            result.append(
                Entity(
                    type=kind,
                    surface=raw[start:end],
                    canonical_value=value,
                    unit=unit,
                    polarity=polarity,
                    source_segment_id=segment.segment_id,
                    source_span=(start, end),
                    start_sec=segment.start_sec,
                    end_sec=segment.end_sec,
                    alternatives=alternatives or [],
                )
            )

        for kind, cue in self.numeric_cues.items():
            for match in re.finditer(cue, text):
                tail = text[match.end() :]
                prefix = re.match(r"[\s:=,\-]*(?:(?:set|to|at|на|установить)\s+)?", tail)
                begin = match.end() + (prefix.end() if prefix else 0)
                tokens = list(re.finditer(r"\d+(?:[.,]\d+)?|[a-zа-яё]+", text[begin:]))
                accepted = []
                previous_end = 0
                for token in tokens:
                    if text[begin + previous_end : begin + token.start()].strip(" -"):
                        break
                    word = token.group()
                    if word in NUMBERS or word in SCALES or re.fullmatch(r"\d+(?:[.,]\d+)?", word):
                        accepted.append(token)
                        previous_end = token.end()
                    else:
                        break
                    if len(accepted) >= 8:
                        break
                if not accepted:
                    continue
                end = begin + accepted[-1].end()
                value, alternatives = parse_number(raw[begin:end])
                unit_match = re.match(
                    r"\s*(knots?|kts|узл\w*|feet|ft|фут\w*|meters?|metres?|метр\w*|degrees?|градус\w*)\b",
                    text[end:],
                )
                unit = None
                if unit_match:
                    unit_token = unit_match.group(1)
                    unit = (
                        "knots"
                        if re.match(r"knots?|kts|узл", unit_token)
                        else "ft"
                        if re.match(r"feet|ft|фут", unit_token)
                        else "m"
                        if re.match(r"met|метр", unit_token)
                        else "degrees"
                    )
                add(kind, begin, end, value, unit, alternatives)
        for match in re.finditer(
            r"\b(?:gear|шасси)\s+(?:(?:not|не)\s+)?(up|down|убран\w*|выпущен\w*)\b", text
        ):
            gear_value = "up" if re.match(r"up|убран", match.group(1)) else "down"
            add("gear_position_mention", match.start(1), match.end(1), gear_value)
        for match in re.finditer(r"\b(?:checklist|чек[ -]?лист)\b", text):
            add("checklist_name", match.start(), match.end(), "unspecified")
        for match in re.finditer(
            r"\b(?:warning|caution|stall|fire|предупрежден\w*|пожар\w*|сваливан\w*)\b", text
        ):
            add("warning_mention", match.start(), match.end(), match.group())
        return sorted(result, key=lambda e: e.source_span)


class EventClassifier:
    version = "rules_v1"
    patterns = {
        "CHECKLIST": r"\b(?:checklist|check list|чек[ -]?лист|карта проверок)\b",
        "CONFIGURATION_MENTION": r"\b(?:flaps?|gear|autopilot|закрылк\w*|шасси|автопилот)\b",
        "REPORTED_DEVIATION": r"\b(?:too high|too low|unstable|слишком высоко|слишком низко|нестабил\w*)\b",
        "WARNING_MENTION": r"\b(?:warning|caution|stall|fire|пожар\w*|сваливан\w*|предупрежден\w*)\b",
        "CREW_COORDINATION": r"\b(?:your controls|my controls|you have control|i have control|crosscheck|confirm|управление у|подтверди\w*|проверь\w*)\b",
    }

    def predict(self, text: str, role: str = "unknown") -> dict[str, Any]:
        labels = [
            label for label, pattern in self.patterns.items() if re.search(pattern, text.casefold())
        ]
        if role == "instructor" and re.search(
            r"\b(?:try again|repeat|повтори\w*|еще раз|ещё раз)\b", text.casefold()
        ):
            labels.append("INSTRUCTOR_FEEDBACK")
        return {
            "labels": labels or ["OTHER"],
            "label_scores": {},
            "salient_for_review": "unknown",
            "classifier_version": self.version,
        }


class ReviewPolicy:
    version = "review_heuristic_v1"

    def apply(self, segment: Segment, entities: list[Entity]) -> None:
        reasons = set(segment.risk_reasons)
        if segment.avg_logprob is not None and segment.avg_logprob < -0.8:
            reasons.add("low_asr_logprob")
        if segment.speaker_id is None:
            reasons.add("unknown_speaker")
        if segment.language not in {"en", "ru"}:
            reasons.add("unvalidated_language")
        if any(
            e.type in {"speed_mention", "altitude_mention", "heading_mention"} and e.unit is None
            for e in entities
        ):
            reasons.add("unit_not_stated")
        if any(e.canonical_value is None for e in entities):
            reasons.add("ambiguous_entity")
        segment.risk_reasons = sorted(reasons)
        segment.risk_level = (
            "high"
            if reasons & {"critical_value_disagreement", "overlap", "ambiguous_entity"}
            else "medium"
        )


class EpisodeBuilder:
    version = "pause_turn_episodes_v1"

    def build(
        self, segments: list[Segment], config: PipelineConfig, classifier=None
    ) -> list[Event]:
        classifier = classifier or EventClassifier()
        groups: list[list[Segment]] = []
        for segment in sorted(segments, key=lambda s: (s.start_sec, s.segment_id)):
            previous = groups[-1] if groups else []
            should_split = not previous or (
                segment.start_sec - previous[-1].end_sec > config.episode_gap_sec
                or segment.end_sec - previous[0].start_sec > config.episode_max_sec
                or (segment.speaker_id, segment.channel)
                != (previous[-1].speaker_id, previous[-1].channel)
                or sum(len(s.raw_asr_text.split()) for s in previous)
                + len(segment.raw_asr_text.split())
                > config.episode_max_tokens
            )
            if should_split:
                groups.append([segment])
            else:
                groups[-1].append(segment)
        events = []
        extractor, review = EntityExtractor(), ReviewPolicy()
        for index, group in enumerate(groups):
            text = " ".join(s.display_text for s in group)
            entities = []
            for s in group:
                found = extractor.extract(s)
                review.apply(s, found)
                entities.extend(found)
            prediction = classifier.predict(text, role=group[0].role)
            events.append(
                Event(
                    event_id=f"event-{index}",
                    start_sec=group[0].start_sec,
                    end_sec=max(s.end_sec for s in group),
                    evidence_segment_ids=[s.segment_id for s in group],
                    evidence_quote=text,
                    speaker_id=group[0].speaker_id,
                    role=group[0].role,
                    role_provenance=group[0].role_provenance,
                    entities=entities,
                    risk_reasons=sorted({r for s in group for r in s.risk_reasons}),
                    **prediction,
                )
            )
        return events


def import_phase_annotations(events: list[Event], annotations: list[dict[str, Any]]) -> None:
    """Trusted simulator metadata is distinct from speech predictions."""
    phases = {"taxi", "takeoff", "climb", "cruise", "descent", "approach", "landing", "unknown"}
    for annotation in annotations:
        if annotation.get("phase") not in phases or not annotation.get("provenance"):
            raise ValueError("Phase annotations require a valid phase and provenance")
        for event in events:
            if (
                annotation["start_sec"] <= event.start_sec
                and annotation["end_sec"] >= event.end_sec
            ):
                event.flight_phase = annotation["phase"]
                event.phase_source = "confirmed_simulator_metadata:" + annotation["provenance"]

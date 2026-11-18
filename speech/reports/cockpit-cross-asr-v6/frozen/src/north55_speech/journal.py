from __future__ import annotations

import csv
import io
import json


def csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


def timestamp(seconds: float, decimal: str = ".") -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal}{millis:03d}"


def export_result(result: dict, format: str) -> tuple[str, str]:
    if format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2), "application/json"
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            [
                "event_id",
                "start_sec",
                "end_sec",
                "labels",
                "quote",
                "salient_for_review",
                "review_status",
                "assertion_kind",
                "entities",
            ]
        )
        for event in result.get("events", []):
            writer.writerow(
                [
                    csv_safe(event.get("event_id")),
                    event["start_sec"],
                    event["end_sec"],
                    csv_safe("|".join(event["labels"])),
                    csv_safe(
                        event.get("reviewed_evidence_quote")
                        if event.get("reviewed_evidence_quote") is not None
                        else event["evidence_quote"]
                    ),
                    event["salient_for_review"],
                    event["review_status"],
                    "spoken_mention",
                    csv_safe(json.dumps(event["entities"], ensure_ascii=False)),
                ]
            )
        return "\ufeff" + stream.getvalue(), "text/csv; charset=utf-8"
    if format in {"vtt", "srt"}:
        lines = ["WEBVTT", ""] if format == "vtt" else []
        for number, segment in enumerate(result.get("segments", []), 1):
            if format == "srt":
                lines.append(str(number))
            decimal = "." if format == "vtt" else ","
            lines.append(
                f"{timestamp(segment['start_sec'], decimal)} --> {timestamp(segment['end_sec'], decimal)}"
            )
            text = (
                segment.get("reviewed_text")
                if segment.get("reviewed_text") is not None
                else segment["display_text"]
            )
            lines.extend([text.replace("-->", "→").replace("\n", " "), ""])
        return "\n".join(
            lines
        ), "text/vtt; charset=utf-8" if format == "vtt" else "application/x-subrip"
    raise ValueError("Unsupported export format")

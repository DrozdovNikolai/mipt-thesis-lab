from scripts.align_annotation_drafts import match_context, tokens


def test_exact_anchor_timeline_and_unsafe_numbers_are_not_rewritten():
    draft = {"segments": [{"words": [
        {"word": "flaps", "start_sec": 1, "end_sec": 2},
        {"word": "fifty", "start_sec": 2, "end_sec": 3},
        {"word": "gear", "start_sec": 4, "end_sec": 5},
        {"word": "down", "start_sec": 5, "end_sec": 6},
    ]}]}
    document = {"blocks": [{"text": "flaps fifteen gear down", "page": 1}]}
    result = match_context(draft, document, 30)
    assert result["coverage"] == 0.5
    assert result["anchors"][0]["exact_tokens"] == ["gear", "down"]
    assert result["anchors"][0]["original_start_sec"] == 34
    assert result["anchors"][0]["original_end_sec"] == 36
    assert draft["segments"][0]["words"][1]["word"] == "fifty"
    assert tokens("Не 15 — пятьдесят") == ["не", "15", "пятьдесят"]


def test_empty_draft_does_not_invent_script_alignment():
    assert match_context({"segments": []}, {"blocks": [{"text": "gear down"}]}, 30)["anchors"] == []

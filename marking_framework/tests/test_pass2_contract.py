import json

import pytest

from scripts.pass2_contract import (
    build_pass2_repair_prompt,
    normalize_full_ranking,
    pass2_text_format,
)


def test_pass2_text_format_schema_shape():
    fmt = pass2_text_format()
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"]["required"] == ["ranking"]


def test_build_pass2_repair_prompt_contains_missing_ids():
    prompt = build_pass2_repair_prompt(["s1", "s2"], "bad", ["s2"])
    assert "Missing IDs: s2" in prompt
    assert "Return ONLY a ranked list" in prompt
    prompt2 = build_pass2_repair_prompt(["s1"], "bad", [])
    assert "Missing IDs:" not in prompt2


def test_normalize_full_ranking_accepts_json_and_text():
    ids = ["s1", "s2", "s3"]
    payload = json.dumps({"ranking": ["s2", "s1", "s3"]})
    ranking, missing = normalize_full_ranking(payload, ids)
    assert ranking == ["s2", "s1", "s3"]
    assert missing == []

    ranking2, missing2 = normalize_full_ranking("s3\ns2\ns1\n", ids)
    assert ranking2 == ["s3", "s2", "s1"]
    assert missing2 == []


def test_normalize_full_ranking_with_missing_and_bad_json():
    ids = ["s1", "s2"]
    ranking, missing = normalize_full_ranking('{"ranking":["s1"]}', ids)
    assert ranking == ["s1"]
    assert missing == ["s2"]
    with pytest.raises(ValueError):
        normalize_full_ranking('{"ranking":["unknown"]}', ids)

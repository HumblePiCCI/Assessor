import json
from pathlib import Path

import scripts.scope_retrieval as sr


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_scope_retrieval_accepts_supported_family(tmp_path):
    metadata = tmp_path / "inputs" / "class_metadata.json"
    routing = tmp_path / "config" / "llm_routing.json"
    rubric = tmp_path / "inputs" / "rubric.md"
    rubric_manifest = tmp_path / "outputs" / "rubric_manifest.json"
    normalized_rubric = tmp_path / "outputs" / "normalized_rubric.json"
    exemplars = tmp_path / "inputs" / "exemplars" / "grade_6_7" / "literary_analysis"
    calibration_manifest = tmp_path / "outputs" / "calibration_manifest.json"
    local_prior = tmp_path / "outputs" / "local_teacher_prior.json"
    cost_limits = tmp_path / "config" / "cost_limits.json"
    exemplars.mkdir(parents=True, exist_ok=True)
    for idx in range(3):
        (exemplars / f"level_{idx + 1}.md").write_text("anchor", encoding="utf-8")
    rubric.write_text("rubric", encoding="utf-8")
    _write_json(metadata, {"grade_level": 7, "grade_band": "grade_6_7", "genre": "literary_analysis"})
    _write_json(routing, {"tasks": {"pass1_assessor": {"model": "gpt-5.4-mini"}}})
    _write_json(rubric_manifest, {"rubric_family": "rubric_unknown"})
    _write_json(normalized_rubric, {"criteria": [{"name": "Ideas"}, {"name": "Organization"}]})
    _write_json(
        calibration_manifest,
        {
            "synthetic": False,
            "scope_coverage": [
                {"key": "grade_6_7|literary_analysis|rubric_unknown|gpt-5.4-mini", "grade_band": "grade_6_7", "genre": "literary_analysis", "rubric_family": "rubric_unknown", "model_family": "gpt-5.4-mini", "samples": 8, "observations": 12},
                {"key": "grade_6_7|literary_analysis|rubric_unknown|gpt-5.4-mini-b", "grade_band": "grade_6_7", "genre": "literary_analysis", "rubric_family": "rubric_unknown", "model_family": "gpt-5.4-mini", "samples": 6, "observations": 10},
            ],
        },
    )
    _write_json(local_prior, {})
    _write_json(cost_limits, {"per_student_max_usd": 0.25})

    payload = sr.build_scope_grounding(
        metadata_path=metadata,
        routing_path=routing,
        rubric_path=rubric,
        rubric_manifest_path=rubric_manifest,
        normalized_rubric_path=normalized_rubric,
        exemplars_root=tmp_path / "inputs" / "exemplars",
        calibration_manifest_path=calibration_manifest,
        local_prior_path=local_prior,
        cost_limits_path=cost_limits,
    )

    assert payload["accepted"] is True
    assert payload["familiarity_label"] == "familiar"
    assert payload["committee_mode_recommended"] is False

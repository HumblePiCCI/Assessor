import json
from pathlib import Path

from scripts import source_calibration as sc


MANIFEST = Path(__file__).resolve().parents[1] / "inputs" / "calibration_sources" / "writing_assessment_sources.json"


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_valid_and_copyright_safe():
    payload = load_manifest()
    assert sc.validate_source_calibration(payload) == []
    raw = json.dumps(payload).lower()
    assert "student_response" not in raw
    assert "full_response" not in raw
    assert "essay_text" not in raw


def test_literary_middle_grade_selection_prioritizes_annotated_core_sources():
    payload = load_manifest()
    selected = sc.selected_sources(payload, genre="literary_analysis", grade_level=7, max_sources=5)
    ids = [item["id"] for item in selected]
    assert ids[0] == "new_meridian_parcc_g7_lat_4127"
    assert "massachusetts_wsa_g7_monsters_c712" in ids
    assert "college_board_ap_literature_samples" not in ids[:3]


def test_high_school_literary_selection_includes_stretch_sources():
    payload = load_manifest()
    selected = sc.selected_sources(payload, genre="literary_analysis", grade_level=11, max_sources=8)
    ids = {item["id"] for item in selected}
    assert "college_board_ap_literature_samples" in ids
    assert "cambridge_igcse_literature_ecr" in ids


def test_source_calibration_rules_filter_by_genre():
    payload = load_manifest()
    literary_rules = sc.selected_rules(payload, genre="literary_analysis", grade_level=7, max_sources=4, max_rules=20)
    argumentative_rules = sc.selected_rules(payload, genre="argumentative", grade_level=8, max_sources=6, max_rules=20)
    literary_text = " ".join(rule["rule"] for rule in literary_rules)
    argumentative_sources = {rule["source_id"] for rule in argumentative_rules}
    assert "literary" in literary_text.lower() or "textual" in literary_text.lower()
    assert "massachusetts_wsa_g8_literary_interpretation_b85" in argumentative_sources


def test_format_source_calibration_lines_includes_guard_and_no_verbatim_samples():
    payload = load_manifest()
    lines = sc.format_source_calibration_lines(payload, genre="literary_analysis", grade_level=7, max_sources=3, max_rules=6)
    joined = "\n".join(lines)
    assert "do not quote, reproduce, or infer any full source essay text" in joined
    assert "Source-derived calibration rules:" in joined
    assert "new_meridian_parcc_g7_lat_4127" in joined
    assert "Massachusetts" in joined


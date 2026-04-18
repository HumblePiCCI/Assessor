import csv
import json
from pathlib import Path

from scripts import committee_edge_resolver as cer


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "committee_edge"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def base_rows():
    return [
        {
            "student_id": "s015",
            "seed_rank": "2",
            "consensus_rank": "2",
            "adjusted_level": "3",
            "composite_score": "0.60",
            "borda_percent": "0.60",
        },
        {
            "student_id": "s009",
            "seed_rank": "3",
            "consensus_rank": "3",
            "adjusted_level": "3",
            "composite_score": "0.91",
            "borda_percent": "0.92",
        },
        {
            "student_id": "s013",
            "seed_rank": "5",
            "consensus_rank": "5",
            "adjusted_level": "3",
            "composite_score": "0.80",
            "borda_percent": "0.80",
        },
        {
            "student_id": "s003",
            "seed_rank": "6",
            "consensus_rank": "6",
            "adjusted_level": "3",
            "composite_score": "0.70",
            "borda_percent": "0.70",
        },
    ]


def fixture_payload():
    return json.loads((FIXTURE_DIR / "escalated_ghost_mini.json").read_text(encoding="utf-8"))


def surface_texts():
    return {
        "s015": "\n\n".join(
            [
                "First, Ghost has consequences. He steals shoes. He runs fast. He learns a lesson. The paragraph is organized and complete.",
                "Second, Coach gives consequences. The team helps. Ghost changes. This paragraph has clean transitions and a clear topic sentence.",
                "Another reason is consequences. Ghost gets in trouble. He works hard. The essay stays neat and easy to follow.",
                "In conclusion, Ghost learns about consequences. The final paragraph repeats the claim with polished control.",
            ]
        ),
        "s009": (
            "Ghost keeps running because fear controls him after the gunshot. "
            "Coach's support reveals that trust is what lets him face consequences. "
            "This demonstrates growth because accountability becomes a way to heal."
        ),
        "s013": "Kyle explains support because it changes Ghost.",
        "s003": "Easton summarizes the plot.",
    }


def test_passthrough_when_no_decisions_preserves_checks_identical(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    payload = fixture_payload()
    escalated.write_text(json.dumps(payload), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, base_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    for student_id, text in surface_texts().items():
        (processing / f"{student_id}.txt").write_text(text, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--escalated",
            str(escalated),
            "--scores",
            str(scores),
            "--class-metadata",
            str(inputs / "class_metadata.json"),
            "--texts",
            str(processing),
            "--candidates-output",
            str(outputs / "committee_edge_candidates.json"),
            "--decisions-output",
            str(outputs / "committee_edge_decisions.json"),
            "--report-output",
            str(outputs / "committee_edge_report.json"),
            "--merged-output",
            str(outputs / "consistency_checks.committee_edge.json"),
        ],
    )

    assert cer.main() == 0
    merged = json.loads((outputs / "consistency_checks.committee_edge.json").read_text(encoding="utf-8"))
    decisions = json.loads((outputs / "committee_edge_decisions.json").read_text(encoding="utf-8"))
    assert merged["checks"] == payload["checks"]
    assert merged["committee_edge"]["passthrough"] is True
    assert decisions["decisions"] == []


def test_trigger_polish_bias_suspected_selects_pair():
    payload = fixture_payload()
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    candidate = next(item for item in candidates if item["pair_key"] == "s009::s015")
    assert "polish_bias_suspected" in candidate["triggers"]
    assert "rougher_but_stronger_latent" in candidate["triggers"]
    assert candidate["selection_status"] == ""


def test_trigger_rougher_but_stronger_latent_requires_aggregate_support():
    payload = fixture_payload()
    positive = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(min_trigger_score=1),
        texts_by_id=surface_texts(),
    )
    assert "rougher_but_stronger_latent" in next(item for item in positive if item["pair_key"] == "s009::s015")["triggers"]

    rows = base_rows()
    for row in rows:
        if row["student_id"] == "s009":
            row["composite_score"] = "0.50"
            row["borda_percent"] = "0.50"
    negative = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=rows,
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(min_trigger_score=1),
        texts_by_id=surface_texts(),
    )
    assert "rougher_but_stronger_latent" not in next(item for item in negative if item["pair_key"] == "s009::s015")["triggers"]


def test_trigger_escalated_vs_direct_matrix_conflict():
    payload = fixture_payload()
    matrix = {
        "comparisons": [
            {
                "pair": ["s015", "s009"],
                "left_over_right_weight": 0.0,
                "right_over_left_weight": 2.0,
            }
        ]
    }
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix=matrix,
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    assert "escalated_vs_direct_matrix_conflict" in next(item for item in candidates if item["pair_key"] == "s009::s015")["triggers"]


def test_trigger_cohort_confidence_missing_is_silent():
    assert cer.load_optional_json(Path("/definitely/not/here.json")) == {}
    payload = fixture_payload()
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    assert all("cohort_confidence_unstable" not in item["triggers"] for item in candidates)


def test_budget_caps_enforced_per_bucket():
    candidates = [
        {
            "pair_key": f"s{i}::t{i}",
            "committee_score": 100 - i,
            "bucket": "top_pack",
            "seed_order": {"higher_rank": i + 1, "lower_rank": i + 2},
        }
        for i in range(3)
    ]
    selected, skipped, budget = cer.select_within_budget(
        candidates,
        config=cer.CandidateConfig(max_candidates=3, max_top_pack=1),
    )
    assert len(selected) == 1
    assert len(skipped) == 2
    assert skipped[0]["skip_reason"] == "max_top_pack_committee_edges_exceeded"
    assert budget["selected_bucket_counts"]["top_pack"] == 1


def test_committee_score_is_deterministic_under_input_reordering():
    payload = fixture_payload()
    kwargs = dict(
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    first = cer.build_candidates(escalated_checks=payload["checks"], **kwargs)
    second = cer.build_candidates(escalated_checks=list(reversed(payload["checks"])), **kwargs)
    assert first == second


def test_min_trigger_score_filters_weak_signals():
    check = {
        "pair": ["s013", "s003"],
        "seed_order": {"higher": "s013", "lower": "s003", "higher_rank": 5, "lower_rank": 6},
        "winner_side": "A",
        "decision": "KEEP",
        "confidence": "high",
        "decision_basis": "content_reasoning",
        "model_metadata": {"adjudication_source": "escalated_adjudication"},
    }
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    assert candidates == []


def test_already_committee_edge_source_is_not_a_candidate():
    check = fixture_payload()["checks"][0]
    check = {**check, "model_metadata": {"adjudication_source": "committee_edge"}}
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(min_trigger_score=1),
        texts_by_id=surface_texts(),
    )
    assert candidates == []


# -----------------------------------------------------------------------------
# Phase 2a: Ghost residual coverage
# -----------------------------------------------------------------------------

GHOST_RESIDUAL_PAIR_KEYS = (
    "s003::s009",
    "s003::s013",
    "s004::s008",
    "s009::s015",
    "s019::s022",
)


def ghost_residual_payload():
    return json.loads((FIXTURE_DIR / "ghost_residual_escalated.json").read_text(encoding="utf-8"))


def ghost_residual_rows():
    """Rows covering all eight residual students plus level/rank metadata.

    Adjusted levels intentionally create level_cross on s019::s022 and
    s004::s008 so the never_escalated_high_leverage trigger has a leverage
    signal to latch onto. s003::s009 stays intra-level because the
    escalated caution + loser-interpretation signal already drives the
    caution_raised trigger without needing a level cross.
    """
    return [
        {"student_id": "s015", "seed_rank": "1", "consensus_rank": "1",
         "adjusted_level": "3", "composite_score": "0.78", "borda_percent": "0.78"},
        {"student_id": "s003", "seed_rank": "4", "consensus_rank": "4",
         "adjusted_level": "3", "composite_score": "0.75", "borda_percent": "0.75"},
        {"student_id": "s022", "seed_rank": "7", "consensus_rank": "7",
         "adjusted_level": "3", "composite_score": "0.70", "borda_percent": "0.70"},
        {"student_id": "s009", "seed_rank": "9", "consensus_rank": "9",
         "adjusted_level": "3", "composite_score": "0.68", "borda_percent": "0.68"},
        {"student_id": "s004", "seed_rank": "10", "consensus_rank": "10",
         "adjusted_level": "3", "composite_score": "0.66", "borda_percent": "0.66"},
        {"student_id": "s019", "seed_rank": "12", "consensus_rank": "12",
         "adjusted_level": "2", "composite_score": "0.60", "borda_percent": "0.60"},
        {"student_id": "s013", "seed_rank": "14", "consensus_rank": "14",
         "adjusted_level": "3", "composite_score": "0.58", "borda_percent": "0.58"},
        {"student_id": "s008", "seed_rank": "18", "consensus_rank": "18",
         "adjusted_level": "2", "composite_score": "0.55", "borda_percent": "0.55"},
    ]


def ghost_residual_texts():
    """Synthetic texts whose surface features mirror the Ghost residual pattern.

    Design targets (verified against literary_surface_features.compute_surface_features):
    - s015: polish-heavy (6 paragraphs, formulaic markers, 0 interpretive verbs).
      surface_delta vs s009 is >= 1.0 → surface_substance_inversion can fire.
    - s009: short, high interpretive density (~1.75, 7 verbs) — stronger interpretation.
    - s003: plot-summary style, 0 verbs, low density.
    - s013: moderate density; Tier 0 (polished_but_shallow) doesn't require density dominance.
    - s022 / s019: s019 is interpretive-dense, s022 is surface-controlled — mirrors the
      Ghost orientation_audit SWAP that flipped s022→s019 despite s022 being the gold winner.
    - s004 / s008: s008 has 6+ more interpretive verbs than s004, so loser-dominant holds
      via the verb-delta path even when density is close.
    """
    return {
        "s015": "\n\n".join(
            [
                "First, Ghost has consequences. Ghost learns an important lesson. The opening paragraph establishes the claim and the organization is tidy.",
                "Second, Coach gives consequences. The team helps Ghost. Ghost changes. This paragraph has clean transitions and a clear topic sentence.",
                "Third, Ghost faces choices. He runs fast. He works hard. He pays consequences. The essay stays neat and easy to follow.",
                "Another reason is consequences. Ghost gets in trouble. He keeps running. He faces the team.",
                "Finally, Ghost accepts consequences. The paragraph uses clean phrasing.",
                "In conclusion, Ghost learns about consequences. The final paragraph restates the claim with polished control and clean sentences.",
            ]
        ),
        "s009": (
            "Ghost keeps running because fear controls him after the gunshot. "
            "Coach support reveals that trust is what lets him face consequences. "
            "This demonstrates growth because accountability becomes a way to heal. "
            "The gunshot suggests that trauma shapes every choice, which means the story proves healing is possible."
        ),
        "s003": (
            "Easton summarizes the plot. Ghost joins the track team. He runs track and causes problems. "
            "Coach gives him tough love. Ghost learns about consequences."
        ),
        "s013": (
            "Kyle writes about identity. Ghost wants to be someone else. He chooses to run. "
            "The team gives him a place to belong because he needs it."
        ),
        "s022": (
            "Sienna is careful and controlled. Ghost runs track. He makes choices. Coach helps. "
            "The story ends with growth because Ghost works hard."
        ),
        "s019": (
            "Naomi explores many ideas because Ghost is complicated. Fear reveals that pain controls him. "
            "The gunshot suggests trauma. Track symbolizes escape. Coach proves support matters. "
            "His stealing illustrates shame, which means every choice represents survival. "
            "The evidence demonstrates that healing requires trust."
        ),
        "s004": (
            "Farris writes a short summary. Ghost runs track because he needs a place. He causes trouble. "
            "Coach supports him. The book ends with growth."
        ),
        "s008": (
            "Hudson attempts a leadership theme because Ghost struggles to lead himself. "
            "His choices reveal fear but suggest growth. Track demonstrates that effort represents healing. "
            "The story shows that leadership means taking responsibility even when it is hard."
        ),
    }


def test_phase2a_triggers_all_five_ghost_residuals():
    """All five Ghost residual pair keys must land in caution_ignored and clear the budget."""
    payload = ghost_residual_payload()
    config = cer.CandidateConfig()
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=ghost_residual_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=config,
        texts_by_id=ghost_residual_texts(),
    )
    by_key = {candidate["pair_key"]: candidate for candidate in candidates}
    for pk in GHOST_RESIDUAL_PAIR_KEYS:
        assert pk in by_key, f"missing candidate for {pk}"
        candidate = by_key[pk]
        assert candidate["bucket"] == "caution_ignored", (
            f"{pk}: expected caution_ignored bucket, got {candidate['bucket']}"
        )
        assert candidate["committee_score"] >= config.caution_ignored_min_trigger_score, (
            f"{pk}: score {candidate['committee_score']} below caution_ignored threshold"
        )
        triggers = set(candidate["triggers"])
        assert triggers & cer.CAUTION_IGNORED_TRIGGERS, (
            f"{pk}: no caution-ignored trigger fired (triggers={sorted(triggers)})"
        )
    selected, skipped, _budget = cer.select_within_budget(candidates, config=config)
    selected_keys = {candidate["pair_key"] for candidate in selected}
    for pk in GHOST_RESIDUAL_PAIR_KEYS:
        assert pk in selected_keys, (
            f"{pk} was not selected within Phase 2a budget "
            f"(skipped={[c['pair_key'] for c in skipped]})"
        )


def test_phase2a_never_escalated_pair_enters_candidate_pool():
    """A never-escalated orientation_audit / cheap_pairwise pair must fire the
    never_escalated_high_leverage trigger and land in the caution_ignored bucket
    — these are pairs the escalation routing never saw but the product still
    cares about because the cheap judge explicitly flagged rougher-stronger risk.
    """
    payload = ghost_residual_payload()
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=ghost_residual_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=ghost_residual_texts(),
    )
    # orientation_audit SWAP branch: s019::s022
    s019 = next(c for c in candidates if c["pair_key"] == "s019::s022")
    assert "never_escalated_high_leverage" in s019["triggers"]
    assert s019["trigger_details"]["winner_source"] == "orientation_audit"
    assert s019["trigger_details"]["non_escalated_source"] is True
    assert s019["bucket"] == "caution_ignored"
    # cheap_pairwise KEEP branch: s004::s008
    s004 = next(c for c in candidates if c["pair_key"] == "s004::s008")
    assert "never_escalated_high_leverage" in s004["triggers"]
    assert s004["trigger_details"]["winner_source"] == "cheap_pairwise"
    assert s004["bucket"] == "caution_ignored"


def test_phase2a_caution_raised_but_polish_like_fires_when_cheap_judge_left_it():
    """cheap_pairwise KEEP that explicitly raised polished_but_shallow should
    fire caution_raised_but_winner_polish_like (Tier 0 priority in the bucket)
    even without density dominance on the loser side — polished_but_shallow is
    such a rare, high-signal caution that any KEEP that raised it is suspect.
    """
    check = {
        "pair": ["s003", "s013"],
        "seed_order": {"higher": "s003", "lower": "s013", "higher_rank": 4, "lower_rank": 14},
        "winner_side": "A",
        "decision": "KEEP",
        "winner": "s003",
        "loser": "s013",
        "confidence": "high",
        "decision_basis": "content_reasoning",
        "cautions_applied": ["polished_but_shallow"],
        "model_metadata": {"adjudication_source": "cheap_pairwise"},
    }
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=ghost_residual_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=ghost_residual_texts(),
    )
    candidate = next(c for c in candidates if c["pair_key"] == "s003::s013")
    assert "caution_raised_but_winner_polish_like" in candidate["triggers"]
    assert candidate["bucket"] == "caution_ignored"
    # Tier 0 is reserved for polished_but_shallow + KEEP (rare, highest-signal pattern)
    assert candidate["caution_ignored_priority_tier"] == 0
    assert candidate["trigger_details"]["polished_but_shallow_raised"] is True
    assert candidate["trigger_details"]["keep_decision"] is True


def test_phase2a_rougher_stronger_latent_deduped_when_caution_trigger_fires():
    """When the explicit caution trigger fires, the latent (aggregate-based)
    trigger encodes the same signal and is removed to prevent score stacking
    from elevating borderline pairs above the residual patterns.
    """
    check = {
        "pair": ["s015", "s009"],
        "seed_order": {"higher": "s015", "lower": "s009", "higher_rank": 1, "lower_rank": 9},
        "winner_side": "A",
        "decision": "KEEP",
        "winner": "s015",
        "loser": "s009",
        "confidence": "medium",
        "decision_basis": "evidence_development",
        "cautions_applied": ["incomplete_or_scaffold"],
        "model_metadata": {"adjudication_source": "escalated_adjudication"},
    }
    # Flip composite/borda so the loser outscores the winner on aggregate
    # — this is the precondition for rougher_but_stronger_latent to fire.
    rows = ghost_residual_rows()
    for row in rows:
        if row["student_id"] == "s009":
            row["composite_score"] = "0.95"
            row["borda_percent"] = "0.95"
        elif row["student_id"] == "s015":
            row["composite_score"] = "0.55"
            row["borda_percent"] = "0.55"
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=rows,
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=ghost_residual_texts(),
    )
    candidate = next(c for c in candidates if c["pair_key"] == "s009::s015")
    # The caution trigger must be present; the latent trigger must be suppressed.
    assert "caution_raised_but_ignored_rougher_stronger" in candidate["triggers"]
    assert "rougher_but_stronger_latent" not in candidate["triggers"]


def test_phase2a_candidate_priority_handles_non_int_tier_values():
    """candidate_priority must not crash on malformed priority-tier values.

    Regression guard for the falsy-int bug: earlier code used
    `tier = int(candidate.get(..., 3) or 3)` which (a) collapsed tier 0
    (a falsy int) to tier 3, and (b) would crash on non-numeric values.
    The current implementation returns tier=3 on both None and non-numeric.
    """
    # Tier 0 must remain tier 0 (not collapse to 3 via falsy-int short-circuit).
    tier0 = {
        "pair_key": "a::b",
        "bucket": "caution_ignored",
        "committee_score": 100,
        "seed_order": {"higher_rank": 1, "lower_rank": 2},
        "caution_ignored_priority_tier": 0,
    }
    # Non-numeric tier falls back to tier 3.
    bad_tier = {
        "pair_key": "c::d",
        "bucket": "caution_ignored",
        "committee_score": 100,
        "seed_order": {"higher_rank": 3, "lower_rank": 4},
        "caution_ignored_priority_tier": "not-a-number",
    }
    # Non-caution_ignored bucket forces tier=3 regardless of stored tier.
    not_caution = {
        "pair_key": "e::f",
        "bucket": "top_pack",
        "committee_score": 100,
        "seed_order": {"higher_rank": 5, "lower_rank": 6},
        "caution_ignored_priority_tier": 0,
    }
    assert cer.candidate_priority(tier0)[0] == 0
    assert cer.candidate_priority(bad_tier)[0] == 3
    assert cer.candidate_priority(not_caution)[0] == 3


def test_phase2a_surface_substance_inversion_fires_without_any_caution():
    """surface_substance_inversion is the broadest Phase 2a heuristic — it must
    fire on pairs with NO caution raised at all when the gap geometry shows
    polish-over-substance. The trigger must land the pair in the caution_ignored
    bucket (so it is always bucket-capped) and emit a heavily-logged detail entry.
    """
    check = {
        "pair": ["s015", "s009"],
        "seed_order": {"higher": "s015", "lower": "s009", "higher_rank": 1, "lower_rank": 9},
        "winner_side": "A",
        "decision": "KEEP",
        "winner": "s015",
        "loser": "s009",
        "confidence": "medium",
        # content_reasoning basis avoids polish_bias_suspected (which is
        # basis-filtered to organization/language_control) — the test isolates
        # surface_substance_inversion as the only caution-ignored-family trigger.
        "decision_basis": "content_reasoning",
        "cautions_applied": [],
        "model_metadata": {"adjudication_source": "escalated_adjudication"},
    }
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=ghost_residual_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=ghost_residual_texts(),
    )
    candidate = next(c for c in candidates if c["pair_key"] == "s009::s015")
    triggers = set(candidate["triggers"])
    assert "surface_substance_inversion" in triggers
    # No caution was raised — this must be the only Phase 2a caution-family trigger.
    assert "caution_raised_but_winner_polish_like" not in triggers
    assert "caution_raised_but_ignored_rougher_stronger" not in triggers
    # Bucket must be caution_ignored so the surface_substance_inversion fires are
    # always bucket-capped and never flood the overall candidate pool.
    assert candidate["bucket"] == "caution_ignored"
    # Heavy logging: the surface_substance_inversion_log records the deltas,
    # cautions, and source every time the trigger fires — even with no caution.
    log = candidate["trigger_details"].get("surface_substance_inversion_log")
    assert log is not None, "surface_substance_inversion_log must be attached"
    assert log["any_caution_raised"] is False
    assert log["surface_delta"] >= cer.CandidateConfig.polish_bias_surface_sd
    assert log["substance_delta"] <= 0.0
    assert log["cautions_raised"] == []
    assert log["winner_source"] == "escalated_adjudication"


def test_decisions_fixture_supersedes_escalated_in_merged_file(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    escalated.write_text(json.dumps(fixture_payload()), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, base_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    for student_id, text in surface_texts().items():
        (processing / f"{student_id}.txt").write_text(text, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--escalated",
            str(escalated),
            "--scores",
            str(scores),
            "--class-metadata",
            str(inputs / "class_metadata.json"),
            "--texts",
            str(processing),
            "--decisions",
            str(FIXTURE_DIR / "committee_decisions_one_override.json"),
            "--candidates-output",
            str(outputs / "committee_edge_candidates.json"),
            "--decisions-output",
            str(outputs / "committee_edge_decisions.json"),
            "--report-output",
            str(outputs / "committee_edge_report.json"),
            "--merged-output",
            str(outputs / "consistency_checks.committee_edge.json"),
        ],
    )

    assert cer.main() == 0
    merged = json.loads((outputs / "consistency_checks.committee_edge.json").read_text(encoding="utf-8"))
    assert merged["committee_edge"]["passthrough"] is False
    assert merged["committee_edge"]["decision_count"] == 1
    assert merged["checks"][0]["model_metadata"]["superseded_by_committee_edge"] is True
    assert merged["checks"][-1]["model_metadata"]["adjudication_source"] == "committee_edge"
    assert merged["checks"][-1]["winner"] == "s009"


def test_merged_file_has_expected_top_level_keys():
    payload = fixture_payload()
    merged = cer.merged_checks_payload(
        escalated_payload=payload,
        escalated_checks=payload["checks"],
        decisions=[],
        candidates=[],
        budget={"selected": 0, "skipped": 0},
    )
    assert {"generated_at", "checks", "pairwise_escalation", "committee_edge"} <= set(merged)
    assert merged["committee_edge"]["phase"] == 1


def test_main_returns_1_when_escalated_file_missing(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--escalated",
            str(tmp_path / "missing.json"),
            "--report-output",
            str(report),
        ],
    )
    assert cer.main() == 1
    assert "not found" in json.loads(report.read_text(encoding="utf-8"))["error"]

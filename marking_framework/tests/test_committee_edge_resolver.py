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


# -----------------------------------------------------------------------------
# Phase 2b: single blind committee Read A
# -----------------------------------------------------------------------------


def test_phase2b_live_flag_off_preserves_phase1_passthrough(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    payload = ghost_residual_payload()
    escalated.write_text(json.dumps(payload), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, ghost_residual_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    for student_id, text in ghost_residual_texts().items():
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
    assert decisions["read_a"]["enabled"] is False
    assert decisions["decisions"] == []


def test_phase2b_blind_read_a_override_rule_applied():
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
    candidate = next(c for c in candidates if c["pair_key"] == "s009::s015")

    def read(winner, confidence="medium", **checks):
        return cer.normalize_committee_read(
            candidate,
            {
                "winner": winner,
                "confidence": confidence,
                "decision_basis": "content_reasoning",
                "decision_checks": {
                    "deeper_interpretation": "B",
                    "better_text_evidence_explanation": "B",
                    "cleaner_or_more_formulaic": "A",
                    "rougher_but_stronger_content": "B",
                    "completion_advantage": "tie",
                    "cleaner_wins_on_substance": "",
                    "rougher_loses_because": "",
                    "interpretation_depth": "B",
                    "proof_sufficiency": "B",
                    "polish_trap": False,
                    "rougher_but_stronger_latent": False,
                    "alternate_theme_validity": "B",
                    "mechanics_block_meaning": False,
                    "completion_floor_applied": False,
                    **checks,
                },
            },
        )

    assert cer.read_a_override_decision(candidate, read("s009", polish_trap=True)) == (
        True,
        "committee_read_a_override",
    )
    assert cer.read_a_override_decision(candidate, read("s009", rougher_but_stronger_latent=True)) == (
        True,
        "committee_read_a_override",
    )
    assert cer.read_a_override_decision(candidate, read("s009", confidence="high", interpretation_depth="B")) == (
        True,
        "committee_read_a_override",
    )
    assert cer.read_a_override_decision(candidate, read("s009", confidence="low", polish_trap=True))[1] == "committee_read_a_low_confidence"
    assert cer.read_a_override_decision(candidate, read("s009", polish_trap=True, mechanics_block_meaning=True))[1] == "committee_read_a_blocked_by_mechanics_or_completion"
    assert cer.read_a_override_decision(candidate, read("s009", confidence="high", interpretation_depth="tie"))[1] == "committee_read_a_inconclusive"


def test_phase2b_read_a_concurrence_does_not_override():
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
    candidate = next(c for c in candidates if c["pair_key"] == "s009::s015")
    read = cer.normalize_committee_read(
        candidate,
        {
            "winner": "s015",
            "confidence": "high",
            "decision_basis": "evidence_development",
            "decision_checks": {
                "interpretation_depth": "A",
                "proof_sufficiency": "A",
                "polish_trap": False,
                "rougher_but_stronger_latent": False,
                "alternate_theme_validity": "A",
                "mechanics_block_meaning": False,
                "completion_floor_applied": False,
            },
        },
    )
    assert cer.read_a_override_decision(candidate, read) == (False, "committee_read_a_concurred")


def test_phase2b_budget_cap_on_live_reads():
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
    selected, _skipped, _budget = cer.select_within_budget(candidates, config=cer.CandidateConfig())
    fixture = cer.load_blind_read_fixture(FIXTURE_DIR / "ghost_residual_blind_reads.json")
    decisions, read_results, summary = cer.run_read_a_path(
        selected=selected,
        rows=ghost_residual_rows(),
        texts_by_id=ghost_residual_texts(),
        rubric="",
        outline="",
        metadata={"assignment_genre": "literary_analysis"},
        model="fixture",
        routing="fixture",
        reasoning="high",
        max_output_tokens=1,
        anchor_dir=FIXTURE_DIR,
        committee_anchor=FIXTURE_DIR / "missing.json",
        max_reads=2,
        live=False,
        fixture_by_key=fixture,
    )
    assert summary["read_count"] == 2
    assert len(decisions) == 2
    assert any(item["status"] == "max_reads_exceeded" for item in read_results)


def test_phase2b_merged_precedence_when_override(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    escalated.write_text(json.dumps(ghost_residual_payload()), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, ghost_residual_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    for student_id, text in ghost_residual_texts().items():
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
            "--blind-read-fixture",
            str(FIXTURE_DIR / "ghost_residual_blind_reads.json"),
            "--max-reads",
            "5",
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
    committee_items = [item for item in merged["checks"] if item.get("model_metadata", {}).get("adjudication_source") == "committee_edge"]
    assert len(committee_items) == 5
    assert decisions["read_a"]["read_count"] == 5
    assert decisions["read_a"]["override_count"] == 5
    assert set(merged["committee_edge"]["superseded_pair_keys"]) == set(GHOST_RESIDUAL_PAIR_KEYS)


def test_phase2b_live_mode_uses_selected_candidates_and_monkeypatched_reader(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    escalated.write_text(json.dumps(ghost_residual_payload()), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, ghost_residual_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    (inputs / "rubric.md").write_text("rubric", encoding="utf-8")
    (inputs / "assignment_outline.md").write_text("outline", encoding="utf-8")
    routing = tmp_path / "config" / "llm_routing.json"
    routing.parent.mkdir()
    routing.write_text(json.dumps({"tasks": {"literary_committee": {"model": "strong", "reasoning": "high", "max_output_tokens": 500}}}), encoding="utf-8")
    for student_id, text in ghost_residual_texts().items():
        (processing / f"{student_id}.txt").write_text(text, encoding="utf-8")

    calls = []

    def fake_read(candidate, rows_by_id, texts, rubric, outline, metadata, **kwargs):
        calls.append(candidate["pair_key"])
        return cer.normalize_committee_read(
            candidate,
            {
                "winner": (candidate["escalated_summary"]["loser"]),
                "confidence": "high",
                "decision_basis": "content_reasoning",
                "decision_checks": {
                    "interpretation_depth": "B",
                    "proof_sufficiency": "B",
                    "polish_trap": True,
                    "rougher_but_stronger_latent": True,
                    "alternate_theme_validity": "B",
                    "mechanics_block_meaning": False,
                    "completion_floor_applied": False,
                },
            },
        )

    monkeypatch.setattr(cer, "run_blind_read_a", fake_read)
    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--live",
            "--max-reads",
            "3",
            "--escalated",
            str(escalated),
            "--scores",
            str(scores),
            "--class-metadata",
            str(inputs / "class_metadata.json"),
            "--texts",
            str(processing),
            "--rubric",
            str(inputs / "rubric.md"),
            "--outline",
            str(inputs / "assignment_outline.md"),
            "--routing",
            str(routing),
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
    decisions = json.loads((outputs / "committee_edge_decisions.json").read_text(encoding="utf-8"))
    assert len(calls) == 3
    assert decisions["read_a"]["live"] is True
    assert decisions["read_a"]["read_count"] == 3
    assert decisions["read_a"]["skipped_max_reads"] > 0


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


# -----------------------------------------------------------------------------
# Phase 3a: multi-read (Read A + Read B polish-trap auditor) + residual-first
# read priority
# -----------------------------------------------------------------------------


def _build_ghost_candidates():
    """Build the full Phase 2a candidate list for the Ghost residual cohort."""
    return cer.build_candidates(
        escalated_checks=ghost_residual_payload()["checks"],
        escalation_candidates={},
        matrix={},
        rows=ghost_residual_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=ghost_residual_texts(),
    )


def _get_candidate(candidates, pair_key):
    return next(c for c in candidates if c["pair_key"] == pair_key)


def _read_a_from_fixture(candidate, fixture_name="ghost_residual_blind_reads.json"):
    fixture = cer.load_blind_read_fixture(FIXTURE_DIR / fixture_name)
    return cer.read_from_fixture(candidate, fixture)


def _make_read(candidate, *, winner, confidence="high", cautions=None, **checks):
    defaults = {
        "deeper_interpretation": "B",
        "better_text_evidence_explanation": "B",
        "cleaner_or_more_formulaic": "A",
        "rougher_but_stronger_content": "B",
        "completion_advantage": "tie",
        "cleaner_wins_on_substance": "",
        "rougher_loses_because": "",
        "interpretation_depth": "B",
        "proof_sufficiency": "B",
        "polish_trap": False,
        "rougher_but_stronger_latent": False,
        "alternate_theme_validity": "B",
        "mechanics_block_meaning": False,
        "completion_floor_applied": False,
    }
    defaults.update(checks)
    return cer.normalize_committee_read(
        candidate,
        {
            "winner": winner,
            "confidence": confidence,
            "decision_basis": "content_reasoning",
            "cautions_applied": list(cautions or []),
            "decision_checks": defaults,
        },
    )


def test_phase3a_read_priority_polished_but_shallow_keep_is_tier_0():
    candidates = _build_ghost_candidates()
    # s003::s013: cheap_pairwise + polished_but_shallow caution + KEEP → Tier 0
    tier_polish = cer.committee_read_priority(_get_candidate(candidates, "s003::s013"))[0]
    assert tier_polish == 0
    # s009::s015: escalated + formulaic_but_thin caution + KEEP → Tier 0 (either polish_like caution qualifies)
    tier_formulaic = cer.committee_read_priority(_get_candidate(candidates, "s009::s015"))[0]
    assert tier_formulaic == 0


def test_phase3a_read_priority_non_escalated_caution_is_tier_1():
    candidates = _build_ghost_candidates()
    # s004::s008: cheap_pairwise + rougher_but_stronger_content + KEEP → Tier 1 (not polish-like caution)
    tier_keep = cer.committee_read_priority(_get_candidate(candidates, "s004::s008"))[0]
    assert tier_keep == 1
    # s019::s022: orientation_audit + rougher_but_stronger_content + SWAP → Tier 1 (non-escalated SWAP)
    tier_swap = cer.committee_read_priority(_get_candidate(candidates, "s019::s022"))[0]
    assert tier_swap == 1


def test_phase3a_read_priority_surface_inversion_without_polish_caution_is_tier_2():
    """A candidate with surface_substance_inversion but no polish/rougher caution and
    an escalated source should land in Tier 2 (not Tier 0/1).
    """
    check = {
        "pair": ["s015", "s009"],
        "seed_order": {"higher": "s015", "lower": "s009", "higher_rank": 1, "lower_rank": 9},
        "winner_side": "A",
        "decision": "KEEP",
        "winner": "s015",
        "loser": "s009",
        "confidence": "medium",
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
    candidate = _get_candidate(candidates, "s009::s015")
    assert "surface_substance_inversion" in candidate["triggers"]
    assert not (set(candidate["trigger_details"]["escalated_cautions"]) & cer.POLISH_LIKE_CAUTIONS)
    assert cer.committee_read_priority(candidate)[0] == 2


def test_phase3a_read_priority_escalated_non_polish_caution_is_tier_3():
    """s003::s009: escalated source + incomplete_or_scaffold + no surface inversion
    → should fall to Tier 3 (remaining caution_ignored)."""
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s003::s009")
    cautions = set(candidate["trigger_details"]["escalated_cautions"])
    # Precondition: not a polish-like caution, not surface inversion.
    assert not (cautions & cer.POLISH_LIKE_CAUTIONS)
    assert "surface_substance_inversion" not in candidate["triggers"]
    assert cer.committee_read_priority(candidate)[0] == 3


def test_phase3a_read_priority_non_caution_ignored_bucket_is_tier_4():
    synthetic = {
        "pair_key": "a::b",
        "bucket": "top_pack",
        "committee_score": 120,
        "seed_order": {"higher_rank": 1, "lower_rank": 2},
        "triggers": ["top10_or_boundary"],
        "trigger_details": {"winner_source": "escalated_adjudication", "keep_decision": True},
    }
    assert cer.committee_read_priority(synthetic)[0] == 4


def test_phase3a_max_reads_reads_all_five_residual_shapes_without_ghost_ids(tmp_path, monkeypatch):
    """Acceptance: given a synthetic cohort where 5 residual-shaped pairs share the
    priority space with 15 non-residual caution_ignored fillers, --max-reads 12
    must read all five residual-shaped pairs. The priority function uses only
    structural signals (cautions, source, decision, SSI trigger); no Ghost IDs.
    """
    residuals = _build_ghost_candidates()
    # Synthetic filler candidates: caution_ignored bucket, Tier 3 (escalated
    # source, no polish-like caution, no SSI, KEEP). Scored below the residual
    # scores so they do not starve the residual reads even when sorted by tier.
    fillers = []
    for i in range(15):
        pair_key = f"f{i:02d}a::f{i:02d}b"
        fillers.append(
            {
                "pair": [f"f{i:02d}a", f"f{i:02d}b"],
                "pair_key": pair_key,
                "bucket": "caution_ignored",
                "committee_score": 75,
                "caution_ignored_priority_tier": 3,
                "triggers": ["caution_raised_but_ignored_rougher_stronger"],
                "seed_order": {
                    "higher": f"f{i:02d}a",
                    "lower": f"f{i:02d}b",
                    "higher_rank": 100 + i,
                    "lower_rank": 120 + i,
                },
                "trigger_details": {
                    "winner_source": "escalated_adjudication",
                    "escalated_cautions": ["incomplete_or_scaffold"],
                    "keep_decision": True,
                    "surface_substance_inversion_log": None,
                },
                "escalated_summary": {
                    "winner": f"f{i:02d}a",
                    "loser": f"f{i:02d}b",
                    "winner_side": "A",
                    "decision": "KEEP",
                    "confidence": "high",
                    "decision_basis": "content_reasoning",
                    "adjudication_source": "escalated_adjudication",
                },
                "selection_status": "selected",
                "selection_reasons": [],
                "surface_features": {"winner": {}, "loser": {}, "gap": {}},
                "skip_reason": "",
            }
        )
    selected = residuals + fillers
    ordered = sorted(selected, key=cer.committee_read_priority)
    top_12_pair_keys = {c["pair_key"] for c in ordered[:12]}
    for pk in GHOST_RESIDUAL_PAIR_KEYS:
        assert pk in top_12_pair_keys, f"residual {pk} not in top 12 reads"


def test_phase3a_should_invoke_read_b_on_a_concur_with_caution_ignored():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    # A concurs with the prior winner (s015) → B must audit because bucket = caution_ignored
    read_a = _make_read(candidate, winner="s015", confidence="high")
    should_run, reason = cer.should_invoke_read_b(candidate, read_a)
    assert should_run is True
    assert reason == "committee_read_b_a_concurred_on_caution_ignored"


def test_phase3a_should_invoke_read_b_on_interp_vs_proof_split():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s019::s022")
    # s019::s022: seed.higher=s022 (A side), seed.lower=s019 (B side). Prior winner=s019.
    # A picks the LOSER per prior (s022) → no concur, so check (1) does not fire.
    # A's own checks show interp favors loser (B=s019) and proof favors winner (A=s022) —
    # the classic polish-trap signature: the pick "wins on proof" but lacks interpretive depth.
    # Escalated cautions include rougher_but_stronger_content (NOT polish-like),
    # so check (3) won't pre-empt check (2).
    read_a = _make_read(
        candidate,
        winner="s022",
        confidence="medium",
        interpretation_depth="B",  # loser side for A.winner=s022
        proof_sufficiency="A",  # winner side for A.winner=s022
    )
    should_run, reason = cer.should_invoke_read_b(candidate, read_a)
    assert should_run is True
    assert reason == "committee_read_b_interp_vs_proof_split"


def test_phase3a_should_invoke_read_b_on_polish_like_caution_present_in_escalated():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s003::s013")  # escalated_cautions includes polished_but_shallow
    read_a = _make_read(candidate, winner="s013", confidence="high")
    should_run, reason = cer.should_invoke_read_b(candidate, read_a)
    assert should_run is True
    assert reason == "committee_read_b_polish_like_caution_raised"


def test_phase3a_should_invoke_read_b_on_rougher_latent_without_override():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s003::s009")
    # A flagged rougher_but_stronger_latent but was LOW conf → Phase 2b gate does not fire
    read_a = _make_read(
        candidate,
        winner="s009",
        confidence="low",  # blocks Phase 2b override even with trap signal
        rougher_but_stronger_latent=True,
    )
    # Preconditions for the test.
    assert cer.read_a_override_decision(candidate, read_a)[0] is False
    should_run, reason = cer.should_invoke_read_b(candidate, read_a)
    assert should_run is True
    assert reason == "committee_read_b_rougher_latent_without_override"


def test_phase3a_should_not_invoke_read_b_when_a_high_conf_clean_interp_to_winner():
    """When A is high conf, interpretation favors winner, and no polish caution is
    present anywhere, Read B should not audit (A already settled the pair clean).
    """
    candidates = _build_ghost_candidates()
    # s019::s022 has escalated_cautions=[rougher_but_stronger_content] (not polish-like).
    candidate = _get_candidate(candidates, "s019::s022")
    read_a = _make_read(
        candidate,
        winner="s022",  # not the prior winner (s019) → a_picked_loser=True
        confidence="high",
        interpretation_depth="A",  # winner_side=A → interp favors winner
        proof_sufficiency="A",
        # No polish_trap / rougher_but_stronger_latent / polish_like caution anywhere on A.
    )
    # Precondition: A overrides under Phase 2b.
    assert cer.read_a_override_decision(candidate, read_a)[0] is True
    should_run, reason = cer.should_invoke_read_b(candidate, read_a)
    assert should_run is False
    assert reason == "committee_read_b_not_needed"


def test_phase3a_resolve_ab_agree_high_conf_emits_override():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s009", confidence="high", polish_trap=True)
    read_b = _make_read(candidate, winner="s009", confidence="high", polish_trap=True)
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert reason == "committee_read_ab_agree_override"
    assert decision is read_b
    assert decision["winner"] == "s009"


def test_phase3a_resolve_ab_agree_medium_conf_requires_polish_trap_signal():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s009", confidence="high")
    # Medium without trap → weak agreement
    read_b_weak = _make_read(candidate, winner="s009", confidence="medium")
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b_weak)
    assert decision is None
    assert reason == "committee_read_ab_weak_agreement"
    # Medium WITH trap → override
    read_b_trap = _make_read(candidate, winner="s009", confidence="medium", polish_trap=True)
    decision2, reason2 = cer.resolve_a_b(candidate, read_a, read_b_trap)
    assert reason2 == "committee_read_ab_agree_override"
    assert decision2 is read_b_trap


def test_phase3a_resolve_ab_agree_low_conf_no_override():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s009", confidence="high")
    read_b = _make_read(candidate, winner="s009", confidence="low", polish_trap=True)
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert decision is None
    assert reason == "committee_read_ab_weak_agreement"


def test_phase3a_resolve_ab_both_concur_with_prior_no_edge():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s015")  # concurs with prior
    read_b = _make_read(candidate, winner="s015")
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert decision is None
    assert reason == "committee_read_ab_concurred"


def test_phase3a_resolve_ab_split_a_loser_b_prior_no_edge():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s009", polish_trap=True)  # A overrides
    read_b = _make_read(candidate, winner="s015", confidence="high", polish_trap=True)  # B reverts
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert decision is None
    assert reason == "committee_read_ab_split_b_confirms_prior"


def test_phase3a_resolve_ab_b_overturns_concur_with_trap_emits_b_override():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s015")  # A concurred with prior
    read_b = _make_read(candidate, winner="s009", confidence="high", polish_trap=True)
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert reason == "committee_read_b_override"
    assert decision is read_b


def test_phase3a_resolve_ab_b_overturns_concur_without_trap_is_ambiguous():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s015")
    read_b = _make_read(candidate, winner="s009", confidence="high")  # no trap flagged
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert decision is None
    assert reason == "committee_read_ab_split_no_trap"


def test_phase3a_resolve_ab_completion_floor_blocks_override():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s009", polish_trap=True)
    read_b = _make_read(
        candidate,
        winner="s009",
        confidence="high",
        polish_trap=True,
        completion_floor_applied=True,
    )
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert decision is None
    assert reason == "committee_read_b_blocked_by_mechanics_or_completion"


def test_phase3a_resolve_ab_mechanics_block_meaning_blocks_override():
    candidates = _build_ghost_candidates()
    candidate = _get_candidate(candidates, "s009::s015")
    read_a = _make_read(candidate, winner="s009", polish_trap=True)
    read_b = _make_read(
        candidate,
        winner="s009",
        confidence="high",
        polish_trap=True,
        mechanics_block_meaning=True,
    )
    decision, reason = cer.resolve_a_b(candidate, read_a, read_b)
    assert decision is None
    assert reason == "committee_read_b_blocked_by_mechanics_or_completion"


def test_phase3a_fixture_ab_all_five_residuals_flip(tmp_path, monkeypatch):
    """End-to-end: with both A and B fixtures, all five Ghost residual-shaped
    pairs flip to the loser. Some flip via A+B agreement (polish-like caution),
    the rest flip via A-only Phase 2b override (B's invocation conditions not met).
    """
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    escalated.write_text(json.dumps(ghost_residual_payload()), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, ghost_residual_rows())
    (inputs / "class_metadata.json").write_text(
        json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8"
    )
    for student_id, text in ghost_residual_texts().items():
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
            "--blind-read-fixture",
            str(FIXTURE_DIR / "ghost_residual_blind_reads.json"),
            "--read-b-fixture",
            str(FIXTURE_DIR / "ghost_residual_read_b.json"),
            "--max-reads",
            "12",
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
    committee_items = [
        item for item in merged["checks"]
        if item.get("model_metadata", {}).get("adjudication_source") == "committee_edge"
    ]
    # All five residual pairs have an override edge.
    assert len(committee_items) == 5
    assert set(merged["committee_edge"]["superseded_pair_keys"]) == set(GHOST_RESIDUAL_PAIR_KEYS)
    # Read A was called at least for all 5; Read B ran for at least the 2 pairs
    # where polish-like cautions trigger invocation (s009::s015 formulaic_but_thin,
    # s003::s013 polished_but_shallow). The other 3 go via A-only.
    assert decisions["read_a"]["read_count"] == 5
    assert decisions["read_a"]["read_b_count"] >= 2
    assert decisions["read_a"]["override_count"] == 5
    # At least the A+B confirmed overrides are tagged phase=3a.
    phase_3a_items = [
        item for item in committee_items
        if str(item.get("model_metadata", {}).get("phase", "")) == "3a"
    ]
    assert len(phase_3a_items) >= 2
    for item in phase_3a_items:
        assert item["model_metadata"]["committee_read"] == "A+B"
        assert "read_a" in item["committee_edge_trace"]
        assert "read_b" in item["committee_edge_trace"]


def test_phase3a_passthrough_preserved_without_fixtures_or_live(tmp_path, monkeypatch):
    """Default (no --live, no fixtures) still yields byte-identical passthrough."""
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    payload = ghost_residual_payload()
    escalated.write_text(json.dumps(payload), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, ghost_residual_rows())
    (inputs / "class_metadata.json").write_text(
        json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8"
    )
    for student_id, text in ghost_residual_texts().items():
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
    assert decisions["read_a"]["enabled"] is False
    assert decisions["read_a"]["read_b_fixture"] is False
    assert decisions["decisions"] == []


def test_phase3a_a_only_fixture_without_b_still_overrides_via_phase2b(tmp_path, monkeypatch):
    """With only --blind-read-fixture (no --read-b-fixture), Phase 2b A-only
    behavior stands. Confirms Phase 3a does not disrupt Phase 2b runs and that
    `read_b_count` is 0.
    """
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    escalated.write_text(json.dumps(ghost_residual_payload()), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, ghost_residual_rows())
    (inputs / "class_metadata.json").write_text(
        json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8"
    )
    for student_id, text in ghost_residual_texts().items():
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
            "--blind-read-fixture",
            str(FIXTURE_DIR / "ghost_residual_blind_reads.json"),
            "--max-reads",
            "12",
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
    decisions = json.loads((outputs / "committee_edge_decisions.json").read_text(encoding="utf-8"))
    assert decisions["read_a"]["read_b_fixture"] is False
    assert decisions["read_a"]["read_b_count"] == 0
    # Phase 2b A-only still emits 5 overrides on the Ghost residual fixture.
    assert decisions["read_a"]["override_count"] == 5

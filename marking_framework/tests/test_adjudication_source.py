from scripts import adjudication_source as src


def test_normalize_source_reads_metadata_block():
    item = {
        "adjudication_source": "cheap_pairwise",
        "model_metadata": {"adjudication_source": "committee_edge"},
    }
    assert src.normalize_source(item) == "committee_edge"


def test_normalize_source_defaults_to_cheap_pairwise():
    assert src.normalize_source({}) == "cheap_pairwise"


def test_normalize_source_orientation_audit_heuristic():
    assert src.normalize_source({"model_metadata": {"orientation_audit": {"status": "conflict"}}}) == "orientation_audit"


def test_precedence_rank_ordering():
    assert src.precedence_rank("committee_edge") < src.precedence_rank("escalated_adjudication")
    assert src.precedence_rank("escalated_adjudication") < src.precedence_rank("orientation_audit")
    assert src.precedence_rank("orientation_audit") < src.precedence_rank("cheap_pairwise")
    assert src.precedence_rank("unknown") > src.precedence_rank("cheap_pairwise")


def test_dedupe_keeps_highest_precedence_per_pair():
    items = [
        {"pair_key": "a::b", "model_metadata": {"adjudication_source": "cheap_pairwise"}, "value": "cheap"},
        {"pair_key": "a::b", "model_metadata": {"adjudication_source": "escalated_adjudication"}, "value": "escalated"},
        {"pair_key": "c::d", "model_metadata": {"adjudication_source": "orientation_audit"}, "value": "audit"},
        {"pair_key": "c::d", "value": "cheap"},
    ]
    kept = src.dedupe_by_precedence(items, key_fn=lambda item: item["pair_key"])
    assert [item["value"] for item in kept] == ["escalated", "audit"]


def test_dedupe_stable_order_within_source_bucket():
    items = [
        {"pair_key": "a::b", "model_metadata": {"adjudication_source": "escalated_adjudication"}, "value": "first"},
        {"pair_key": "a::b", "model_metadata": {"adjudication_source": "escalated_adjudication"}, "value": "second"},
        {"pair_key": "a::b", "model_metadata": {"adjudication_source": "cheap_pairwise"}, "value": "cheap"},
    ]
    kept = src.dedupe_by_precedence(items, key_fn=lambda item: item["pair_key"])
    assert [item["value"] for item in kept] == ["first", "second"]


def test_mark_superseded_sets_metadata_flags():
    items = [
        {"pair": ["a", "b"], "model_metadata": {"adjudication_source": "escalated_adjudication"}},
        {"pair": ["a", "b"], "model_metadata": {"adjudication_source": "committee_edge"}},
    ]
    marked = src.mark_superseded(items, {"a::b": "committee_edge"})
    assert marked[0]["model_metadata"]["superseded_by_committee_edge"] is True
    assert marked[1]["model_metadata"]["superseded_by_committee_edge"] is False
    assert "superseded_by_committee_edge" not in items[0]["model_metadata"]

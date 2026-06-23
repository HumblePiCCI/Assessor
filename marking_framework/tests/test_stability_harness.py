import json

import scripts.stability_harness as sh


def write_fixture(tmp_path):
    rows = [
        {"student_id": f"s{i}", "seed_rank": str(i), "consensus_rank": str(i), "adjusted_level": "3",
         "rubric_after_penalty_percent": str(80 - i), "composite_score": str(0.9 - i * 0.02)}
        for i in range(1, 7)
    ]
    import csv
    scores = tmp_path / "scores.csv"
    with scores.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    checks = [
        {"pair": ["s1", "s2"], "decision": "KEEP", "confidence": "medium", "rationale": "ok"},
        {"pair": ["s2", "s3"], "decision": "KEEP", "confidence": "low", "rationale": "ok"},
        {"pair": ["s3", "s4"], "decision": "SWAP", "confidence": "medium", "rationale": "ok"},
        {"pair": ["s4", "s5"], "decision": "KEEP", "confidence": "high", "rationale": "ok"},
    ]
    judgments = tmp_path / "checks.json"
    judgments.write_text(json.dumps({"checks": checks}), encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    return scores, judgments, config


def test_harness_deterministic_for_same_seed(tmp_path):
    scores, judgments, config = write_fixture(tmp_path)
    kwargs = dict(
        scores_path=scores, judgments_path=judgments, config_path=config,
        cohort_confidence_path=None, seed_trust_mode="adaptive",
        runs=5, flip_rate=0.5, drop_rate=0.2, seed=42,
    )
    a = sh.run_harness(**kwargs)
    b = sh.run_harness(**kwargs)
    assert a == b
    assert a["runs"] == 5
    assert 0 <= a["mean_top5_overlap"] <= 5


def test_perturb_payload_never_touches_high_confidence(tmp_path):
    import random
    payload = {"checks": [
        {"pair": ["a", "b"], "decision": "KEEP", "confidence": "high"},
        {"pair": ["c", "d"], "decision": "KEEP", "confidence": "low"},
    ]}
    rng = random.Random(1)
    flipped_high = False
    for _ in range(50):
        out = sh.perturb_payload(payload, rng, flip_rate=1.0, drop_rate=0.0)
        high = [c for c in out["checks"] if c["pair"] == ["a", "b"]][0]
        if high["decision"] != "KEEP":
            flipped_high = True
    assert not flipped_high

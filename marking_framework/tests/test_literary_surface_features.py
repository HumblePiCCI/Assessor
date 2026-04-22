from scripts.literary_surface_features import compute_surface_features, polish_vs_substance_gap


def test_compute_surface_features_basic_counts():
    text = "Ghost changes because he learns trust.\n\nThis reveals accountability."
    features = compute_surface_features(text)
    assert features.word_count == 9
    assert features.paragraph_count == 2
    assert features.thesis_like_sentence_count == 2
    assert features.interpretive_verb_count == 2
    assert features.interpretive_density == 1.0


def test_interpretive_density_rewards_analytical_verbs():
    summary = compute_surface_features("Ghost runs. Coach talks. The race happens.")
    analysis = compute_surface_features("Ghost runs because fear controls him. This reveals how trust changes him.")
    assert analysis.interpretive_density > summary.interpretive_density
    assert analysis.interpretive_verb_count > summary.interpretive_verb_count


def test_polish_vs_substance_gap_flags_clean_but_thin():
    polished = compute_surface_features(
        "\n\n".join(
            [
                "First, Ghost has consequences. He steals shoes. He runs fast. He learns a lesson.",
                "Second, Ghost has more consequences. Coach helps him. The team is important. Ghost changes.",
                "Another reason is consequences. Ghost gets in trouble. He works hard. In conclusion he grows.",
            ]
        )
    )
    rougher = compute_surface_features(
        "Ghost hides his fear because running away feels safe. This reveals that trust changes him. "
        "Coach's support demonstrates that accountability can heal him because Ghost finally faces what happened."
    )
    gap = polish_vs_substance_gap(polished, rougher)
    assert gap["surface_delta"] > 0
    assert gap["substance_delta"] < 0
    assert gap["polish_bias_flag"] is True


def test_polish_vs_substance_gap_no_flag_when_both_substantive():
    left = compute_surface_features(
        "Ghost changes because Coach makes him accountable. This reveals that consequences can build trust."
    )
    right = compute_surface_features(
        "Ghost grows because he stops hiding. This demonstrates that support helps him face fear."
    )
    assert polish_vs_substance_gap(left, right)["polish_bias_flag"] is False

import re

from scripts.levels import level_to_percent


PROFILE_WEIGHTS = {
    "A": (0.36, 0.24, 0.20, 0.20),
    "B": (0.24, 0.24, 0.16, 0.36),
    "C": (0.32, 0.20, 0.30, 0.18),
}
LEVEL_ANCHORS = [54.0, 64.0, 75.0, 84.0, 95.0]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[.!?]+", text) if p.strip()]
    return parts


def _content_score(text: str) -> float:
    words = _words(text)
    markers = len(re.findall(r"\b(first|second|third|because|therefore|for example|for instance|recommend)\b", text.lower()))
    base = 18.0 + min(42.0, len(words) * 0.10) + min(32.0, markers * 5.5)
    return _clamp(base)


def _organization_score(text: str) -> float:
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    has_opening = bool(re.search(r"(?i)\b(dear|to\s+the\s+principal|i\s+am\s+writing)\b", text))
    has_closing = bool(re.search(r"(?i)\b(sincerely|in conclusion|thank you)\b", text))
    markers = len(re.findall(r"\b(first|second|third|another|finally|therefore|because)\b", text.lower()))
    para_score = min(36.0, len(paragraphs) * 8.0)
    open_close = 12.0 * float(has_opening) + 12.0 * float(has_closing)
    seq_score = min(40.0, markers * 8.0)
    return _clamp(para_score + open_close + seq_score)


def _style_score(text: str) -> float:
    words = _words(text)
    if not words:
        return 0.0
    unique_ratio = len(set(w.lower() for w in words)) / max(1, len(words))
    sentences = _sentences(text)
    avg_len = len(words) / max(1, len(sentences))
    variety = 52.0 * min(1.0, unique_ratio / 0.62)
    flow = 48.0 * min(1.0, avg_len / 18.0)
    return _clamp(variety + flow)


def _conventions_score(text: str) -> float:
    words = _words(text)
    if not words:
        return 0.0
    miss_end = 0 if text.strip().endswith((".", "!", "?")) else 1
    lower_starts = sum(1 for s in _sentences(text) if s and s[0].islower())
    double_space = text.count("  ")
    penalties = (miss_end * 4.0) + (lower_starts * 2.0) + (double_space * 1.5)
    return _clamp(100.0 - penalties)


def _token_set(text: str) -> set[str]:
    return {w.lower() for w in _words(text) if len(w) > 3}


def _feature_profile(text: str) -> dict[str, float]:
    words = _words(text)
    sentences = _sentences(text)
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    markers = len(re.findall(r"\b(first|second|third|because|therefore|however|for example|for instance|finally)\b", text.lower()))
    evidence = len(re.findall(r"[\"“”]|according to|percent|data|study|source", text.lower()))
    unique_ratio = len(set(w.lower() for w in words)) / max(1, len(words))
    return {
        "word_count": float(len(words)),
        "sentence_count": float(len(sentences)),
        "paragraph_count": float(len(paragraphs)),
        "avg_sentence_len": float(len(words) / max(1, len(sentences))),
        "unique_ratio": float(unique_ratio),
        "marker_density": float(markers / max(1, len(sentences))),
        "evidence_density": float(evidence / max(1, len(sentences))),
    }


def _profile_distance(a: dict[str, float], b: dict[str, float]) -> float:
    scales = {
        "word_count": 220.0,
        "sentence_count": 18.0,
        "paragraph_count": 6.0,
        "avg_sentence_len": 18.0,
        "unique_ratio": 0.5,
        "marker_density": 2.0,
        "evidence_density": 2.0,
    }
    total = 0.0
    for key, scale in scales.items():
        total += abs(float(a.get(key, 0.0)) - float(b.get(key, 0.0))) / scale
    return total / len(scales)


def _level_from_exemplar_key(key: str) -> str | None:
    lookup = {
        "level_1": "1",
        "level_2": "2",
        "level_3": "3",
        "level_4": "4",
        "level_4_plus": "4+",
    }
    return lookup.get(key)


def _level_rank(percent: float | None) -> int | None:
    if percent is None:
        return None
    value = float(percent)
    nearest = min(range(len(LEVEL_ANCHORS)), key=lambda idx: abs(LEVEL_ANCHORS[idx] - value))
    return nearest


def _structure_target(text: str, exemplars: dict[str, str] | None) -> tuple[float | None, float]:
    if not exemplars:
        return None, 0.0
    text_profile = _feature_profile(text)
    best_target = None
    best_distance = None
    for key, sample in exemplars.items():
        level = _level_from_exemplar_key(key)
        if not level or not sample.strip():
            continue
        sample_profile = _feature_profile(sample)
        distance = _profile_distance(text_profile, sample_profile)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_target = level_to_percent(level)
    if best_target is None:
        return None, 0.0
    confidence = _clamp(1.0 - (float(best_distance) / 0.85), 0.0, 1.0)
    return best_target, confidence


def _weighted_structure_target(text: str, exemplars: dict[str, str] | None) -> tuple[float | None, float]:
    if not exemplars:
        return None, 0.0
    text_profile = _feature_profile(text)
    candidates = []
    level_keys = [("level_1", "1"), ("level_2", "2"), ("level_3", "3"), ("level_4", "4"), ("level_4_plus", "4+")]
    for key, level in level_keys:
        sample = exemplars.get(key, "")
        if not sample.strip():
            continue
        sample_profile = _feature_profile(sample)
        distance = _profile_distance(text_profile, sample_profile)
        candidates.append((distance, level_to_percent(level)))
    if not candidates:
        return None, 0.0
    candidates.sort(key=lambda pair: pair[0])
    top = candidates[:3]
    best_rank = _level_rank(top[0][1])
    if best_rank is not None:
        nearby = []
        for item in top:
            item_rank = _level_rank(item[1])
            if item_rank is None:
                item_rank = best_rank
            if abs(item_rank - best_rank) <= 1:
                nearby.append(item)
        if nearby:
            top = nearby
    temperature = 0.12
    weights = [2.718281828 ** (-(distance / temperature)) for distance, _ in top]
    total_w = sum(weights)
    target = sum(weight * level for weight, (_, level) in zip(weights, top)) / max(total_w, 1e-6)
    best = top[0][0]
    second = top[1][0] if len(top) > 1 else best + 0.5
    margin = max(0.0, second - best)
    confidence = (0.70 * _clamp(1.0 - (best / 0.90), 0.0, 1.0)) + min(0.30, margin / 0.40)
    return _clamp(target), _clamp(confidence, 0.0, 1.0)


def _exemplar_target(text: str, exemplars: dict[str, str] | None) -> tuple[float | None, float]:
    if not exemplars:
        return None, 0.0
    target = None
    best_overlap = 0.0
    base = _token_set(text)
    if not base:
        return None, 0.0
    level_keys = [("level_1", "1"), ("level_2", "2"), ("level_3", "3"), ("level_4", "4"), ("level_4_plus", "4+")]
    for key, level in level_keys:
        sample = exemplars.get(key, "")
        if not sample.strip():
            continue
        ref = _token_set(sample)
        if not ref:
            continue
        overlap = len(base & ref) / max(1, len(base | ref))
        if overlap > best_overlap:
            best_overlap = overlap
            target = level_to_percent(level)
    return target, best_overlap


def _boundary_adjust(score: float, target_hint: float | None, target_conf: float = 0.0) -> float:
    if target_hint is None:
        return score
    adjusted = float(score)
    for boundary in (60.0, 70.0, 80.0, 90.0):
        delta = adjusted - boundary
        if abs(delta) <= 1.25:
            if target_hint >= boundary:
                adjusted = max(adjusted, boundary + 0.35)
            else:
                adjusted = min(adjusted, boundary - 0.35)
            continue
        # Near-miss uplift: prevent stable under-placement when an anchor sits just below a boundary.
        if (
            -3.6 <= delta < 0.0
            and target_conf >= 0.55
            and target_hint >= (boundary - 2.0)
        ):
            adjusted = max(adjusted, boundary + 0.25)
    return adjusted


def deterministic_score(text: str, assessor_id: str, exemplars: dict[str, str] | None = None) -> float:
    weights = PROFILE_WEIGHTS.get(str(assessor_id).upper(), PROFILE_WEIGHTS["A"])
    content = _content_score(text)
    org = _organization_score(text)
    style = _style_score(text)
    conv = _conventions_score(text)
    final = (weights[0] * content) + (weights[1] * org) + (weights[2] * style)
    final += (conv - 70.0) * (weights[3] * 0.9)
    structure_target, structure_conf = _weighted_structure_target(text, exemplars)
    if structure_target is None:
        structure_target, structure_conf = _structure_target(text, exemplars)
    if structure_target is not None:
        # Structure-based anchor keeps bands stable across sessions and prompts.
        blend = 0.62 + (0.28 * structure_conf)
        final = (1.0 - blend) * final + (blend * structure_target)
    target, overlap = _exemplar_target(text, exemplars)
    structure_rank = _level_rank(structure_target)
    target_rank = _level_rank(target)
    lexical_compatible = (
        structure_rank is None
        or target_rank is None
        or abs(target_rank - structure_rank) <= 1
    )
    if target is not None and overlap >= 0.02 and lexical_compatible:
        if overlap < 0.08:
            blend = 0.08
        elif overlap < 0.14:
            blend = 0.18
        elif overlap < 0.30:
            blend = 0.32
        elif overlap < 0.60:
            blend = 0.55
        else:
            blend = 0.80
        final = (1.0 - blend) * final + (blend * target)
    hint_conf = structure_conf if structure_target is not None else overlap
    final = _boundary_adjust(final, structure_target or target, hint_conf)
    return round(_clamp(final), 2)


def _criterion_score(criterion_id: str, overall: float, content: float, org: float, style: float, conv: float) -> float:
    token = re.sub(r"[^A-Za-z0-9+]", "", str(criterion_id or "").upper())
    if token.startswith("K"):
        value = 0.75 * overall + 0.25 * content
    elif token.startswith("T"):
        value = 0.80 * overall + 0.20 * style
    elif token == "C1":
        value = 0.80 * overall + 0.20 * org
    elif token == "C2":
        value = 0.65 * overall + 0.35 * conv
    elif token == "C3":
        value = 0.80 * overall + 0.20 * style
    elif token.startswith("A"):
        value = 0.80 * overall + 0.20 * content
    elif token in {"LA1", "AR1", "NR1"}:
        value = 0.80 * overall + 0.20 * org
    elif token in {"LA2", "AR2", "IR3", "NR3"}:
        value = 0.80 * overall + 0.20 * content
    elif token in {"LA3", "AR3"}:
        value = 0.80 * overall + 0.20 * style
    elif token in {"IR1", "NR2"}:
        value = 0.80 * overall + 0.20 * conv
    elif token == "IR2":
        value = 0.80 * overall + 0.20 * org
    else:
        value = overall
    return _clamp(value)


def _normalize_criteria_to_overall(criteria: dict[str, float], overall: float) -> dict[str, float]:
    if not criteria:
        return {}
    normalized = {key: _clamp(value) for key, value in criteria.items()}
    for _ in range(2):
        current = sum(normalized.values()) / len(normalized)
        delta = float(overall) - current
        if abs(delta) < 0.01:
            break
        normalized = {key: _clamp(value + delta) for key, value in normalized.items()}
    return {key: round(value, 2) for key, value in normalized.items()}


def deterministic_pass1_item(student_id: str, text: str, assessor_id: str, required_ids: list[str] | None = None,
                             exemplars: dict[str, str] | None = None) -> dict:
    score = deterministic_score(text, assessor_id, exemplars)
    content = _content_score(text)
    org = _organization_score(text)
    style = _style_score(text)
    conv = _conventions_score(text)
    criteria = {}
    req = required_ids or []
    if req:
        for cid in req:
            criteria[cid] = _criterion_score(cid, score, content, org, style, conv)
        criteria = _normalize_criteria_to_overall(criteria, score)
        score = round(sum(criteria.values()) / len(criteria), 2)
    notes = f"Fallback deterministic score for assessor {assessor_id}."
    return {
        "student_id": student_id,
        "rubric_total_points": score,
        "criteria_points": criteria,
        "criteria_evidence": [],
        "notes": notes,
    }


def deterministic_level(score_percent: float) -> str:
    if score_percent >= level_to_percent("4+"):
        return "4+"
    if score_percent >= level_to_percent("4"):
        return "4"
    if score_percent >= level_to_percent("3"):
        return "3"
    if score_percent >= level_to_percent("2"):
        return "2"
    return "1"

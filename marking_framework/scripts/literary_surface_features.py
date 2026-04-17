#!/usr/bin/env python3
"""Deterministic surface-vs-substance features for literary pair routing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


INTERPRETIVE_VERB_RE = re.compile(
    r"\b(suggests?|reveals?|illustrates?|because|demonstrates?|symboli[sz]es?|shows?\s+that|means?|represents?|proves?)\b",
    re.IGNORECASE,
)
FORMULAIC_TOPIC_RE = re.compile(
    r"\b(first|second|third|another|also|finally|in\s+conclusion|to\s+conclude|overall)\b",
    re.IGNORECASE,
)
THESIS_RE = re.compile(
    r"\b(theme|message|lesson|claim|shows?\s+that|reveals?\s+that|proves?\s+that|because|important|changes?|consequence|accountability|trust|support|identity|healing)\b",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-z0-9']+")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


@dataclass(frozen=True)
class SurfaceFeatures:
    word_count: int
    paragraph_count: int
    avg_paragraph_words: float
    thesis_like_sentence_count: int
    quotation_count: int
    interpretive_verb_count: int
    formulaic_topic_sentence_count: int
    interpretive_density: float

    def to_dict(self) -> dict:
        return asdict(self)


def _sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text or "") if match.group(0).strip()]


def _paragraphs(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text or "") if part.strip()]
    return paragraphs or ([text.strip()] if str(text or "").strip() else [])


def compute_surface_features(text: str) -> SurfaceFeatures:
    raw = text or ""
    words = WORD_RE.findall(raw)
    sentences = _sentences(raw)
    paragraphs = _paragraphs(raw)
    paragraph_count = len(paragraphs)
    avg_paragraph_words = len(words) / max(1, paragraph_count)
    first_sentences = sentences[:3]
    thesis_like_sentence_count = sum(1 for sentence in first_sentences if THESIS_RE.search(sentence))
    quotation_count = raw.count('"') + raw.count("'") + raw.count("“") + raw.count("”") + raw.count("‘") + raw.count("’")
    interpretive_verb_count = len(INTERPRETIVE_VERB_RE.findall(raw))
    formulaic_topic_sentence_count = sum(1 for sentence in sentences if FORMULAIC_TOPIC_RE.search(sentence[:80]))
    interpretive_density = interpretive_verb_count / max(1, len(sentences))
    return SurfaceFeatures(
        word_count=len(words),
        paragraph_count=paragraph_count,
        avg_paragraph_words=round(avg_paragraph_words, 6),
        thesis_like_sentence_count=thesis_like_sentence_count,
        quotation_count=quotation_count,
        interpretive_verb_count=interpretive_verb_count,
        formulaic_topic_sentence_count=formulaic_topic_sentence_count,
        interpretive_density=round(interpretive_density, 6),
    )


def _surface_score(features: SurfaceFeatures) -> float:
    return (
        min(features.word_count / 450.0, 1.5)
        + min(features.paragraph_count / 5.0, 1.2)
        + (0.25 * features.thesis_like_sentence_count)
        + (0.15 * features.formulaic_topic_sentence_count)
    )


def _substance_score(features: SurfaceFeatures) -> float:
    return (features.interpretive_density * 4.0) + (0.15 * features.interpretive_verb_count) + min(features.quotation_count / 8.0, 0.75)


def polish_vs_substance_gap(winner: SurfaceFeatures, loser: SurfaceFeatures) -> dict:
    surface_delta = round(_surface_score(winner) - _surface_score(loser), 6)
    substance_delta = round(_substance_score(winner) - _substance_score(loser), 6)
    return {
        "surface_delta": surface_delta,
        "substance_delta": substance_delta,
        "polish_bias_flag": bool(surface_delta >= 0.25 and substance_delta <= -0.50),
    }

#!/usr/bin/env python3
"""Shared judgment-source normalization and precedence helpers."""

from __future__ import annotations

import copy
from collections.abc import Callable


SOURCE_PRECEDENCE = (
    "committee_edge",
    "escalated_adjudication",
    "orientation_audit",
    "cheap_pairwise",
)


def pair_key_from_item(item: dict) -> str:
    explicit = str(item.get("pair_key") or "").strip()
    if explicit:
        return explicit
    pair = item.get("pair")
    if isinstance(pair, list) and len(pair) == 2:
        left = str(pair[0] or "").strip()
        right = str(pair[1] or "").strip()
        if left and right:
            return "::".join(sorted((left, right)))
    seed_order = item.get("seed_order") if isinstance(item.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    if higher and lower:
        return "::".join(sorted((higher, lower)))
    return ""


def normalize_source(item: dict) -> str:
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    source = str(metadata.get("adjudication_source") or item.get("adjudication_source") or "").strip()
    if source:
        return source
    if isinstance(metadata.get("orientation_audit"), dict):
        return "orientation_audit"
    return "cheap_pairwise"


def precedence_rank(source: str) -> int:
    token = str(source or "").strip()
    try:
        return SOURCE_PRECEDENCE.index(token)
    except ValueError:
        return len(SOURCE_PRECEDENCE)


def dedupe_by_precedence(
    items: list[dict],
    *,
    key_fn: Callable[[dict], str],
    source_fn: Callable[[dict], str] = normalize_source,
) -> list[dict]:
    best_rank_by_key: dict[str, int] = {}
    for item in items:
        key = str(key_fn(item) or "").strip()
        if not key:
            continue
        rank = precedence_rank(source_fn(item))
        if key not in best_rank_by_key or rank < best_rank_by_key[key]:
            best_rank_by_key[key] = rank

    kept = []
    for item in items:
        key = str(key_fn(item) or "").strip()
        if not key:
            kept.append(item)
            continue
        if precedence_rank(source_fn(item)) == best_rank_by_key.get(key, len(SOURCE_PRECEDENCE)):
            kept.append(item)
    return kept


def mark_superseded(items: list[dict], superseded_by: dict[str, str]) -> list[dict]:
    marked = copy.deepcopy(items)
    for item in marked:
        key = pair_key_from_item(item)
        winning_source = str(superseded_by.get(key, "") or "").strip()
        if not winning_source:
            continue
        metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
        metadata = dict(metadata)
        item["model_metadata"] = metadata
        source = normalize_source(item)
        flag = f"superseded_by_{winning_source}"
        metadata[flag] = precedence_rank(source) > precedence_rank(winning_source)
    return marked

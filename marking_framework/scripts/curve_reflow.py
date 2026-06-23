#!/usr/bin/env python3
"""Deterministic pin & re-flow of the grade curve around teacher anchors.

The machine curve (final_grade by rank position) is treated as a shape
function. Teacher pins and curve bounds become anchors; every unpinned mark
re-interpolates along the machine shape between its two nearest anchors, so
the bell keeps its form, order is preserved, and every mark stays explainable
as "the machine shape stretched between the teacher's anchors".

Precedence: order monotonicity > pins > curve bounds > machine shape.
Pins never move; bounds expand to accommodate pins; pin-vs-pin conflicts
require an explicit reorder confirmation (`accept_reorder=True`).

Pure functions only — same inputs always produce the same marks.
"""

from statistics import NormalDist

DEFAULT_TOP = 92.0
DEFAULT_BOTTOM = 58.0


def _num(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _bell_position(index: int, count: int) -> float:
    """Bell-shaped position in [0, 1] for a rank index (1.0 = top)."""
    if count <= 1:
        return 1.0
    low_p = 0.5 / count
    high_p = 1.0 - low_p
    percentile = high_p - (index * (high_p - low_p) / (count - 1))
    dist = NormalDist()
    low_z = dist.inv_cdf(low_p)
    high_z = dist.inv_cdf(high_p)
    curr_z = dist.inv_cdf(percentile)
    if high_z == low_z:
        return 1.0 - (index / (count - 1))
    return (curr_z - low_z) / (high_z - low_z)


def baseline_shape(students: list[dict], curve_top: float | None, curve_bottom: float | None) -> list[float]:
    """Machine marks as a monotone non-increasing function of rank position.

    Prefers the unrounded machine curve (final_grade_raw) so integer-rounding
    plateaus don't flatten the shape, then the rounded final_grade; falls back
    to a bell between the effective bounds when the cohort has no machine
    grades.
    """
    count = len(students)
    if count == 0:
        return []
    marks = [
        _num(s.get("final_grade_raw"), _num(s.get("final_grade")))
        for s in students
    ]
    if any(m is None for m in marks):
        top = _num(curve_top, DEFAULT_TOP)
        bottom = _num(curve_bottom, DEFAULT_BOTTOM)
        return [bottom + (top - bottom) * _bell_position(i, count) for i in range(count)]
    return sorted((float(m) for m in marks), reverse=True)


def normalize_pins(raw_pins, students: list[dict]) -> dict[str, float]:
    known = {str(s.get("student_id", "") or "") for s in students}
    pins: dict[str, float] = {}
    for item in raw_pins or []:
        if isinstance(item, dict):
            sid = str(item.get("student_id", "") or "").strip()
            mark = _num(item.get("mark"))
        else:
            continue
        if not sid or sid not in known or mark is None:
            continue
        pins[sid] = _clamp(round(mark, 4), 0.0, 100.0)
    return pins


def _resolve_order(students: list[dict], pins: dict[str, float], shape: list[float]) -> tuple[list[dict], list[dict]]:
    """Stable-sort students by effective mark; return (new_order, implied_moves)."""
    keyed = []
    for idx, student in enumerate(students):
        sid = str(student.get("student_id", "") or "")
        effective = pins.get(sid, shape[idx])
        keyed.append((-(effective), idx, student))
    keyed.sort(key=lambda item: (item[0], item[1]))
    new_order = [item[2] for item in keyed]
    moves = []
    for new_idx, (_, old_idx, student) in enumerate(keyed):
        if old_idx != new_idx:
            moves.append(
                {
                    "student_id": str(student.get("student_id", "") or ""),
                    "from_rank": old_idx + 1,
                    "to_rank": new_idx + 1,
                }
            )
    return new_order, moves


def _segment_positions(shape: list[float], i0: int, i1: int) -> list[float]:
    """Strictly decreasing interpolation weights for indices i0..i1 inclusive.

    Value-based, so the machine curve's spacing (band cliffs, bell tails)
    survives the stretch — but exact-tie runs are respaced positionally so a
    rounding plateau stretches between the anchors instead of moving as a
    block with a pin.
    """
    n = i1 - i0
    span = shape[i0] - shape[i1]
    if span <= 0:
        return [1.0 - (k / n) for k in range(n + 1)]
    t = [(shape[i0 + k] - shape[i1]) / span for k in range(n + 1)]
    t[0], t[n] = 1.0, 0.0
    for k in range(1, n + 1):
        t[k] = min(t[k - 1], max(0.0, min(1.0, t[k])))
    idx = 0
    while idx <= n:
        end = idx
        while end + 1 <= n and t[end + 1] == t[idx]:
            end += 1
        if end > idx:
            start = max(idx, 1)
            stop = min(end, n - 1)
            if start <= stop:
                hi = t[start - 1]
                lo = t[end + 1] if end + 1 <= n else 0.0
                run = stop - start + 1
                for m in range(run):
                    t[start + m] = hi - ((m + 1) / (run + 1)) * (hi - lo)
        idx = end + 1
    return t


def _identity_result(students: list[dict], shape: list[float], level_bands: list[dict] | None) -> dict:
    results = []
    for idx, student in enumerate(students):
        sid = str(student.get("student_id", "") or "")
        baseline = _num(student.get("final_grade"))
        mark = int(round(baseline if baseline is not None else shape[idx]))
        band = _band_for_level(level_bands, student.get("adjusted_level") or student.get("base_level"))
        band_break = False
        if band is not None:
            band_min = _num(band.get("min"), 0.0)
            band_max = _num(band.get("max"), 100.0)
            band_break = not (band_min <= mark <= band_max)
        results.append(
            {
                "student_id": sid,
                "rank": idx + 1,
                "mark": mark,
                "pinned": False,
                "baseline_mark": baseline,
                "delta": 0 if baseline is not None else None,
                "anchor_above": "machine",
                "anchor_below": "machine",
                "band_break": band_break,
            }
        )
    return {
        "marks": results,
        "order_changed": False,
        "reorder_required": False,
        "implied_moves": [],
        "clamped_pins": [],
        "curve_top": shape[0],
        "curve_bottom": shape[-1],
        "anchors": [],
    }


def _band_for_level(level_bands: list[dict] | None, level) -> dict | None:
    if not level_bands or level in (None, ""):
        return None
    target = str(level).strip().lower()
    for band in level_bands:
        if str(band.get("level", "")).strip().lower() == target:
            return band
    return None


def reflow_marks(
    students: list[dict],
    pins: dict[str, float] | None = None,
    *,
    curve_top: float | None = None,
    curve_bottom: float | None = None,
    accept_reorder: bool = False,
    level_bands: list[dict] | None = None,
) -> dict:
    """Re-flow cohort marks around teacher pins and curve bounds.

    `students` must be in rank order (best first). Returns the marks in the
    effective order, reorder proposals when pins conflict with each other,
    and per-student anchor provenance for explainability.
    """
    pins = dict(pins or {})
    count = len(students)
    if count == 0:
        return {
            "marks": [],
            "order_changed": False,
            "reorder_required": False,
            "implied_moves": [],
            "clamped_pins": [],
            "curve_top": _num(curve_top, DEFAULT_TOP),
            "curve_bottom": _num(curve_bottom, DEFAULT_BOTTOM),
            "anchors": [],
        }

    shape = baseline_shape(students, curve_top, curve_bottom)

    # No teacher input at all: the machine curve passes through untouched.
    if not pins and curve_top is None and curve_bottom is None:
        return _identity_result(students, shape, level_bands)

    # Pins beat bounds: expand effective bounds to honor every pin.
    effective_top = _num(curve_top, shape[0])
    effective_bottom = _num(curve_bottom, shape[-1])
    if effective_top < effective_bottom:
        effective_top, effective_bottom = effective_bottom, effective_top
    if pins:
        effective_top = max(effective_top, max(pins.values()))
        effective_bottom = min(effective_bottom, min(pins.values()))

    # Detect pin-vs-pin conflicts: do pins imply a different order?
    ordered = list(students)
    implied_moves: list[dict] = []
    order_changed = False
    pin_positions = [
        (idx, pins[str(s.get("student_id", "") or "")])
        for idx, s in enumerate(ordered)
        if str(s.get("student_id", "") or "") in pins
    ]
    pins_conflict = any(
        earlier_mark < later_mark
        for (_, earlier_mark), (_, later_mark) in zip(pin_positions, pin_positions[1:])
    )
    reorder_required = pins_conflict and not accept_reorder
    if pins_conflict and accept_reorder:
        ordered, implied_moves = _resolve_order(ordered, pins, shape)
        order_changed = bool(implied_moves)
    elif pins_conflict:
        _, implied_moves = _resolve_order(ordered, pins, shape)

    # Build the anchor list top-down: bounds at the extremes unless pinned,
    # pins everywhere they sit. Clamp top-down so anchors never increase;
    # only unconfirmed conflicting pins can get clamped here.
    anchors: list[tuple[int, float, str]] = []
    clamped_pins: list[dict] = []
    first_sid = str(ordered[0].get("student_id", "") or "")
    last_sid = str(ordered[-1].get("student_id", "") or "")
    if first_sid not in pins:
        anchors.append((0, effective_top, "curve_top"))
    for idx, student in enumerate(ordered):
        sid = str(student.get("student_id", "") or "")
        if sid in pins:
            anchors.append((idx, pins[sid], sid))
    if count > 1 and last_sid not in pins:
        anchors.append((count - 1, effective_bottom, "curve_bottom"))

    running = None
    safe_anchors: list[tuple[int, float, str]] = []
    for idx, mark, source in anchors:
        if running is not None and mark > running:
            if source not in ("curve_top", "curve_bottom"):
                clamped_pins.append({"student_id": source, "requested": mark, "applied": running})
            mark = running
        running = mark
        safe_anchors.append((idx, mark, source))

    # Re-flow every unpinned student along the machine shape between its
    # two nearest anchors.
    marks = [0.0] * count
    anchor_above = [""] * count
    anchor_below = [""] * count
    for (i0, m0, s0), (i1, m1, s1) in zip(safe_anchors, safe_anchors[1:]):
        marks[i0], marks[i1] = m0, m1
        anchor_above[i0] = anchor_below[i0] = s0
        anchor_above[i1] = anchor_below[i1] = s1
        positions = _segment_positions(shape, i0, i1)
        for j in range(i0 + 1, i1):
            marks[j] = m1 + positions[j - i0] * (m0 - m1)
            anchor_above[j], anchor_below[j] = s0, s1
    if len(safe_anchors) == 1:
        idx, mark, source = safe_anchors[0]
        marks = [mark] * count
        anchor_above = anchor_below = [source] * count

    # Integer marks, monotone non-increasing (ties allowed).
    rounded = [int(round(m)) for m in marks]
    for idx in range(1, count):
        if rounded[idx] > rounded[idx - 1]:
            rounded[idx] = rounded[idx - 1]

    results = []
    for idx, student in enumerate(ordered):
        sid = str(student.get("student_id", "") or "")
        baseline = _num(student.get("final_grade"))
        band = _band_for_level(level_bands, student.get("adjusted_level") or student.get("base_level"))
        band_break = False
        if band is not None:
            band_min = _num(band.get("min"), 0.0)
            band_max = _num(band.get("max"), 100.0)
            band_break = not (band_min <= rounded[idx] <= band_max)
        results.append(
            {
                "student_id": sid,
                "rank": idx + 1,
                "mark": rounded[idx],
                "pinned": sid in pins,
                "baseline_mark": baseline,
                "delta": (rounded[idx] - baseline) if baseline is not None else None,
                "anchor_above": anchor_above[idx],
                "anchor_below": anchor_below[idx],
                "band_break": band_break,
            }
        )

    return {
        "marks": results,
        "order_changed": order_changed,
        "reorder_required": reorder_required,
        "implied_moves": implied_moves,
        "clamped_pins": clamped_pins,
        "curve_top": effective_top,
        "curve_bottom": effective_bottom,
        "anchors": [
            {"rank": idx + 1, "mark": mark, "source": source} for idx, mark, source in safe_anchors
        ],
    }

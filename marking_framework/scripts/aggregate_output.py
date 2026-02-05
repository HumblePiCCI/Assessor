#!/usr/bin/env python3
import csv
import json
from pathlib import Path


def write_consensus_csv(rows_sorted, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = list(rows_sorted[0].keys()) if rows_sorted else []
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if rows_sorted:
            writer.writeheader()
            writer.writerows(rows_sorted)


def write_ranked_list(rows_sorted, ranked_md: Path):
    with ranked_md.open("w", encoding="utf-8") as f:
        f.write("Consensus Ranking\n\n")
        for row in rows_sorted:
            flags = f" ({row['flags']})" if row["flags"] else ""
            f.write(f"{row['consensus_rank']}. {row['student_id']}{flags}\n")


def write_disagreements(rows_sorted, recon_path: Path):
    disagreements = [r for r in rows_sorted if r["flags"]]
    recon_path.parent.mkdir(parents=True, exist_ok=True)
    with recon_path.open("w", encoding="utf-8") as f:
        f.write("Disagreements / Re-read List\n\n")
        if not disagreements:
            f.write("None.\n")
        else:
            for row in disagreements:
                f.write(f"- {row['student_id']}: {row['flags']}\n")
    return disagreements


def write_irr_metrics(irr, irr_path: Path, student_ids_count, num_assessors_pass1, num_assessors_pass2, rubric_points_possible, flagged_count, penalties_count):
    irr_full = {
        "inter_rater_reliability": irr,
        "assessment_info": {
            "num_students": student_ids_count,
            "num_assessors_pass1": num_assessors_pass1,
            "num_assessors_pass2": num_assessors_pass2,
            "rubric_points_possible": rubric_points_possible,
        },
        "quality_summary": {
            "students_flagged": flagged_count,
            "conventions_penalties": penalties_count,
        },
        "interpretation": {
            "rubric_icc": "excellent" if irr["rubric_icc"] > 0.9 else ("good" if irr["rubric_icc"] > 0.7 else ("fair" if irr["rubric_icc"] > 0.5 else "poor")),
            "rank_agreement": "good" if irr["rank_kendall_w"] > 0.7 else ("fair" if irr["rank_kendall_w"] > 0.5 else "poor"),
        }
    }

    with irr_path.open("w", encoding="utf-8") as f:
        json.dump(irr_full, f, indent=2)
    return irr_full

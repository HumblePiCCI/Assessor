from scripts.portfolio_pieces import (
    aggregate_portfolio_piece_assessments,
    split_portfolio_pieces,
    summarize_portfolio_pieces,
)


def test_split_portfolio_pieces_uses_blank_line_boundaries():
    text = (
        "Poppy and the Beanstalk\nOnce upon a time there was a girl called Poppy.\n\n"
        "Porchester Castle\nYesterday I visited a castle and wrote about it.\n\n"
        "How to Make a Paper Windmill\n1. Fold the paper.\n2. Pin the center."
    )
    pieces = split_portfolio_pieces(text)
    assert [piece["piece_id"] for piece in pieces] == ["p01", "p02", "p03"]
    assert pieces[0]["title"] == "Poppy and the Beanstalk"
    assert pieces[1]["title"] == "Porchester Castle"
    assert pieces[2]["title"] == "How to Make a Paper Windmill"


def test_summarize_portfolio_pieces_mentions_titles():
    pieces = split_portfolio_pieces(
        "First Piece\nThis is the first portfolio response.\n\n"
        "Second Piece\nThis is the second portfolio response."
    )
    summary = summarize_portfolio_pieces(pieces, 220)
    assert "First Piece" in summary
    assert "Second Piece" in summary


def test_aggregate_portfolio_piece_assessments_promotes_consistent_top_profile():
    pieces = split_portfolio_pieces(
        "Opening the Fridge\nA polished narrative.\n\n"
        "The Applause\nA vivid performance recount.\n\n"
        "How Pointe Shoes Came To Be\nA strong explanatory report.\n\n"
        "Dear Diary\nA reflective diary entry."
    )
    piece_items = [
        {"student_id": "s1::p01", "rubric_total_points": 84.0, "criteria_points": {"C1": 83.0}, "notes": "Strong narrative."},
        {"student_id": "s1::p02", "rubric_total_points": 82.0, "criteria_points": {"C1": 81.0}, "notes": "Strong recount."},
        {"student_id": "s1::p03", "rubric_total_points": 77.0, "criteria_points": {"C1": 76.0}, "notes": "Good report."},
        {"student_id": "s1::p04", "rubric_total_points": 79.0, "criteria_points": {"C1": 78.0}, "notes": "Secure diary entry."},
    ]
    item, report = aggregate_portfolio_piece_assessments("s1", pieces, piece_items, "A")
    assert item["portfolio_overall_level"] == "4"
    assert item["rubric_total_points"] >= 80.0
    assert item["portfolio_piece_count"] == 4
    assert "greater depth" in item["notes"].lower()
    assert report["overall_level"] == "4"
    assert len(report["pieces"]) == 4

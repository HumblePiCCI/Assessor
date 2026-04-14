from tests.conftest import make_docx

from scripts.calibration_contract import build_run_scope
import scripts.document_extract as de
import scripts.rubric_contract as rc


def test_build_rubric_artifacts_from_plain_text(tmp_path):
    rubric = tmp_path / "rubric.md"
    rubric.write_text(
        "\n".join(
            [
                "Argument Writing Rubric",
                "Ideas and analysis 30%",
                "Organization 25%",
                "Evidence and support 25%",
                "Conventions 20%",
                "Level 4 80-100: sophisticated and precise",
                "Level 3 70-79: clear and consistent",
                "Level 2 60-69: partial control",
                "Level 1 0-59: limited control",
            ]
        ),
        encoding="utf-8",
    )
    outline = tmp_path / "outline.md"
    outline.write_text("Write an argument using evidence and analysis.", encoding="utf-8")

    artifacts = rc.build_rubric_artifacts(rubric, outline_path=outline)
    assert artifacts["normalized_rubric"]["genre"] == "argumentative"
    assert artifacts["rubric_manifest"]["rubric_family"]
    assert artifacts["rubric_validation_report"]["proceed_mode"] == "auto"
    assert artifacts["rubric_verification"]["status"] == "auto_confirmed"
    assert len(artifacts["normalized_rubric"]["criteria"]) >= 4


def test_extract_document_text_supports_docx_and_rtf(tmp_path):
    docx = make_docx(tmp_path / "rubric.docx", "Docx rubric")
    rtf = tmp_path / "rubric.rtf"
    rtf.write_text(r"{\rtf1\ansi Ideas and organization\par Level 4 80-100}", encoding="utf-8")

    docx_text, docx_meta = rc.extract_document_text(docx)
    rtf_text, rtf_meta = rc.extract_document_text(rtf)

    assert "Docx rubric" in docx_text
    assert "docx_xml" in docx_meta["methods"]
    assert "Level 4" in rtf_text
    assert rtf_meta["source_format"] == "rtf"


def test_extract_document_text_supports_pdf_and_image_via_fallbacks(tmp_path, monkeypatch):
    pdf = tmp_path / "rubric.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    image = tmp_path / "rubric.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(de, "_pdf_to_text", lambda _path: ("PDF rubric text\nLevel 4 80-100", ["pdftotext"]))
    monkeypatch.setattr(de, "_image_to_text", lambda _path: ("OCR rubric text\nIdeas 25%", ["tesseract"]))

    pdf_text, pdf_meta = rc.extract_document_text(pdf)
    image_text, image_meta = rc.extract_document_text(image)

    assert "PDF rubric text" in pdf_text
    assert pdf_meta["methods"] == ["pdftotext"]
    assert "OCR rubric text" in image_text
    assert image_meta["methods"] == ["tesseract"]


def test_pdf_extraction_rejects_raw_pdf_payload_and_uses_ghostscript(tmp_path, monkeypatch):
    pdf = tmp_path / "rubric.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def fake_which(cmd):
        if cmd == "gs":
            return "/opt/homebrew/bin/gs"
        if cmd in {"pdftotext", "textutil", "mdls"}:
            return f"/usr/bin/{cmd}"
        return None

    def fake_run_command(cmd, *, input_path=None):
        joined = " ".join(cmd)
        if "pdftotext" in joined:
            return ""
        if "gs" in joined:
            return "Readable PDF text\nGrade 6: A Summary Report\nLevel 4"
        if "textutil" in joined:
            return "%PDF-1.4\n1 0 obj\n<< /Length 10 /Filter /LZWDecode >>\nstream\nraw\nendstream\nendobj"
        if "mdls" in joined:
            return "(null)"
        return ""

    monkeypatch.setattr(de.shutil, "which", fake_which)
    monkeypatch.setattr(de, "_run_command", fake_run_command)

    pdf_text, pdf_meta = rc.extract_document_text(pdf)

    assert "Readable PDF text" in pdf_text
    assert pdf_meta["methods"] == ["pdftotext", "ghostscript_txtwrite"]


def test_pdf_raw_payload_detector_flags_embedded_pdf_bytes():
    raw_pdf = "%PDF-1.4\n1 0 obj\n<< /Length 10 /Filter /LZWDecode >>\nstream\nraw\nendstream\nendobj\nxref\n%%EOF"
    clean_text = "Grade 1 sample\nTeacher's Notes\nLevel 4"

    assert de._looks_like_raw_pdf_payload(raw_pdf) is True
    assert de._looks_like_raw_pdf_payload(clean_text) is False


def test_build_rubric_artifacts_requires_confirmation_for_empty_rubric(tmp_path):
    rubric = tmp_path / "rubric.md"
    rubric.write_text("", encoding="utf-8")
    artifacts = rc.build_rubric_artifacts(rubric)
    assert artifacts["rubric_validation_report"]["proceed_mode"] == "block"
    assert artifacts["rubric_verification"]["required_confirmation"] is True


def test_teacher_edits_change_manifest_hash(tmp_path):
    rubric = tmp_path / "rubric.md"
    rubric.write_text("Ideas and analysis\nLevel 4 80-100", encoding="utf-8")
    original = rc.build_rubric_artifacts(rubric)
    edited = rc.build_rubric_artifacts(
        rubric,
        teacher_edits={
            "genre": "argumentative",
            "criteria": [{"name": "Insight", "weight": 0.6}, {"name": "Conventions", "weight": 0.4}],
            "levels": [{"label": "4", "band_min": 85, "band_max": 100, "descriptor": "excellent"}],
        },
        action="edit",
    )
    assert original["rubric_manifest"]["manifest_hash"] != edited["rubric_manifest"]["manifest_hash"]
    assert edited["rubric_verification"]["status"] == "edited"
    assert "Insight" in rc.prompt_text_from_normalized(edited["normalized_rubric"], include_raw_text=False)


def test_rubric_manifest_flows_into_run_scope(tmp_path):
    rubric = tmp_path / "rubric.md"
    rubric.write_text("Ideas and analysis\nLevel 4 80-100", encoding="utf-8")
    artifacts = rc.build_rubric_artifacts(rubric, teacher_edits={"genre": "argumentative"}, action="edit")
    scope = build_run_scope(
        metadata={"grade_level": 8},
        routing={"tasks": {"pass1_assessor": {"model": "gpt-5.4"}}},
        rubric_path=rubric,
        rubric_manifest=artifacts["rubric_manifest"],
    )
    assert scope["genre"] == "argumentative"
    assert scope["rubric_family"] == artifacts["rubric_manifest"]["rubric_family"]

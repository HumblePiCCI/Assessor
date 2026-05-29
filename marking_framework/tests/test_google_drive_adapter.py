import io
import zipfile

from server.google_drive_adapter import GoogleDriveAdapter


class Response:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append({"url": url, "params": params or {}})
        return self.responses.pop(0)


def docx_bytes(text):
    buf = io.BytesIO()
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_drive_adapter_exports_google_doc_to_text_and_redacts_file_id():
    adapter = GoogleDriveAdapter(
        "token",
        transport=Transport(
            [
                Response(200, {"id": "real-file-id", "name": "Essay", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-05-29T00:00:00Z"}),
                Response(200, content=b"Google doc essay."),
            ]
        ),
    )
    attachment = adapter.resolve_drive_file("real-file-id")
    assert attachment["support_state"] == "supported"
    assert "Google doc essay." in attachment["text"]
    assert attachment["source_file_id_hash"].startswith("drive:")
    assert "real-file-id" not in str(attachment)


def test_drive_adapter_downloads_plain_text_and_docx():
    text_adapter = GoogleDriveAdapter(
        "token",
        transport=Transport(
            [
                Response(200, {"id": "text-id", "name": "Essay.txt", "mimeType": "text/plain"}),
                Response(200, content=b"Plain essay."),
            ]
        ),
    )
    assert "Plain essay." in text_adapter.resolve_drive_file("text-id")["text"]

    docx_adapter = GoogleDriveAdapter(
        "token",
        transport=Transport(
            [
                Response(200, {"id": "docx-id", "name": "Essay.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
                Response(200, content=docx_bytes("DOCX essay.")),
            ]
        ),
    )
    assert "DOCX essay." in docx_adapter.resolve_drive_file("docx-id")["text"]


def test_drive_adapter_blocks_unsupported_empty_image_external_and_missing_scope():
    for mime_type, blocker in [
        ("application/vnd.google-apps.form", "forms_unsupported"),
        ("application/vnd.google-apps.presentation", "slides_unsupported"),
        ("application/vnd.google-apps.spreadsheet", "sheets_unsupported"),
        ("application/vnd.google-apps.drawing", "drawing_unsupported"),
        ("image/png", "ocr_not_configured"),
    ]:
        adapter = GoogleDriveAdapter("token", transport=Transport([Response(200, {"id": "id", "name": "Attachment", "mimeType": mime_type})]))
        assert adapter.resolve_drive_file("id")["blockers"] == [blocker]

    empty_doc = GoogleDriveAdapter(
        "token",
        transport=Transport(
            [
                Response(200, {"id": "empty", "name": "Empty", "mimeType": "application/vnd.google-apps.document"}),
                Response(200, content=b""),
            ]
        ),
    )
    assert empty_doc.resolve_drive_file("empty")["blockers"] == ["empty_attachment"]

    missing_scope = GoogleDriveAdapter(
        "token",
        transport=Transport(
            [
                Response(
                    403,
                    {"error": {"message": "Request had insufficient authentication scopes.", "errors": [{"reason": "insufficientPermissions"}]}},
                )
            ]
        ),
    )
    assert missing_scope.resolve_classroom_attachment({"driveFile": {"driveFile": {"id": "secret", "title": "Secret"}}})["blockers"] == ["requires_drive_scope"]
    assert GoogleDriveAdapter("token").resolve_classroom_attachment({"link": {"url": "https://example.com"}})["blockers"] == ["external_link_unsupported"]

#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import mimetypes
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from scripts.document_extract import extract_document_text


DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
GOOGLE_EXPORT_BLOCKERS = {
    "application/vnd.google-apps.form": "forms_unsupported",
    "application/vnd.google-apps.presentation": "slides_unsupported",
    "application/vnd.google-apps.spreadsheet": "sheets_unsupported",
    "application/vnd.google-apps.drawing": "drawing_unsupported",
}
TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/html",
    "application/rtf",
}
DOCUMENT_MIME_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag.lower() in {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self._skip_depth:
            text = str(data or "").strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return "\n".join(part.strip() for part in self.parts if part.strip())


class GoogleDriveError(ValueError):
    def __init__(self, message: str, *, code: str = "google_drive_error", status_code: int = 0, reason: str = ""):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.reason = reason


class DriveTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        timeout: float = 30.0,
    ):
        return httpx.request(method, url, headers=headers, params=params, timeout=timeout)


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bytes_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def redacted_file_id(file_id: str) -> str:
    return f"drive:{hashlib.sha256(str(file_id or '').encode('utf-8')).hexdigest()[:24]}"


def _response_json(response: Any) -> dict:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _status_code(response: Any) -> int:
    try:
        return int(response.status_code)
    except Exception:
        return 0


def google_error_code(response: Any, *, default: str = "drive_api_error") -> str:
    status = _status_code(response)
    payload = _response_json(response)
    error = payload.get("error", {}) if isinstance(payload.get("error"), dict) else {}
    reason = ""
    errors = error.get("errors", []) if isinstance(error.get("errors"), list) else []
    if errors and isinstance(errors[0], dict):
        reason = str(errors[0].get("reason", "") or "")
    message = str(error.get("message", "") or payload.get("error_description", "") or "")
    combined = f"{reason} {message}".lower()
    if status == 401:
        if "expired" in combined or "invalid" in combined:
            return "oauth_token_expired"
        return "missing_oauth_grant"
    if "accessnotconfigured" in combined or "api has not been used" in combined or "disabled" in combined:
        return "drive_api_disabled"
    if status in {401, 403} and ("insufficient" in combined or "scope" in combined):
        return "requires_drive_scope"
    if "file too large" in combined or "export size" in combined or "10 mb" in combined or "too large" in combined:
        return "file_too_large"
    if status == 403:
        return "permission_denied"
    if status == 404:
        return "resource_not_found"
    if status == 429 or "quota" in combined or "ratelimit" in combined or "rate limit" in combined:
        return "quota_exhausted"
    if status in {500, 502, 503, 504}:
        return "google_api_unavailable"
    return default


def html_to_text(raw: bytes) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(raw.decode("utf-8", errors="ignore"))
    return parser.text()


class GoogleDriveAdapter:
    def __init__(self, access_token: str, *, transport: DriveTransport | None = None):
        self.access_token = str(access_token or "")
        self.transport = transport or DriveTransport()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, *, params: dict | None = None):
        url = f"{DRIVE_API_BASE}{path}"
        response = self.transport.request(method, url, headers=self._headers(), params=params, timeout=30.0)
        if _status_code(response) >= 400:
            code = google_error_code(response)
            raise GoogleDriveError(f"Google Drive API error: {code}", code=code, status_code=_status_code(response))
        return response

    def get_file_metadata(self, file_id: str) -> dict:
        response = self._request(
            "GET",
            f"/files/{quote(file_id, safe='')}",
            params={
                "fields": "id,name,mimeType,md5Checksum,size,modifiedTime,headRevisionId,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        return _response_json(response)

    def export_file(self, file_id: str, mime_type: str = "text/plain") -> bytes:
        response = self._request(
            "GET",
            f"/files/{quote(file_id, safe='')}/export",
            params={"mimeType": mime_type},
        )
        return bytes(getattr(response, "content", b"") or b"")

    def download_file(self, file_id: str) -> bytes:
        response = self._request(
            "GET",
            f"/files/{quote(file_id, safe='')}",
            params={"alt": "media", "supportsAllDrives": "true"},
        )
        return bytes(getattr(response, "content", b"") or b"")

    def _title(self, metadata: dict, fallback: str) -> str:
        return str(metadata.get("name", "") or fallback or "attachment").strip()

    def _blocked(self, *, file_id: str = "", title: str = "attachment", mime_type: str = "", blocker: str, attachment_type: str = "drive_file") -> dict:
        return {
            "attachment_id": redacted_file_id(file_id or title),
            "title": title,
            "mime_type": mime_type,
            "type": attachment_type,
            "support_state": "unsupported" if blocker not in {"requires_drive_scope", "ocr_not_configured"} else "needs_manual_review",
            "extraction_status": "blocked",
            "blockers": [blocker],
            "unsupported_reason": blocker,
            "source_file_id_hash": redacted_file_id(file_id) if file_id else "",
            "file_hash": "",
            "text_hash": "",
            "text": "",
        }

    def _text_attachment(self, *, file_id: str, title: str, mime_type: str, raw: bytes, text: str, metadata: dict, export_mime_type: str = "") -> dict:
        text = str(text or "").strip()
        if not text:
            return self._blocked(file_id=file_id, title=title, mime_type=mime_type, blocker="no_extractable_text")
        decorated = f"--- Attachment: {title} ---\n{text}"
        return {
            "attachment_id": redacted_file_id(file_id),
            "title": title,
            "mime_type": mime_type,
            "type": "drive_file",
            "support_state": "supported",
            "extraction_status": "extractable_text_available",
            "blockers": [],
            "unsupported_reason": "",
            "source_file_id_hash": redacted_file_id(file_id),
            "source_revision_id": canonical_hash(
                {
                    "headRevisionId": metadata.get("headRevisionId", ""),
                    "modifiedTime": metadata.get("modifiedTime", ""),
                    "size": metadata.get("size", ""),
                }
            )[:24],
            "source_modified_at": str(metadata.get("modifiedTime", "") or ""),
            "file_hash": bytes_hash(raw) if raw else str(metadata.get("md5Checksum", "") or ""),
            "text_hash": canonical_hash({"text": decorated}),
            "export_mime_type": export_mime_type,
            "text": decorated,
        }

    def resolve_drive_file(self, file_id: str, *, fallback_title: str = "attachment") -> dict:
        if not file_id:
            return self._blocked(title=fallback_title, blocker="empty_attachment")
        metadata = self.get_file_metadata(file_id)
        title = self._title(metadata, fallback_title)
        mime_type = str(metadata.get("mimeType", "") or "").lower()
        if mime_type in GOOGLE_EXPORT_BLOCKERS:
            return self._blocked(file_id=file_id, title=title, mime_type=mime_type, blocker=GOOGLE_EXPORT_BLOCKERS[mime_type])
        if mime_type.startswith("image/"):
            return self._blocked(file_id=file_id, title=title, mime_type=mime_type, blocker="ocr_not_configured", attachment_type="image")
        if mime_type == GOOGLE_DOC_MIME_TYPE:
            raw = self.export_file(file_id, "text/plain")
            text = raw.decode("utf-8", errors="ignore")
            if not text.strip():
                return self._blocked(file_id=file_id, title=title, mime_type=mime_type, blocker="empty_attachment")
            return self._text_attachment(
                file_id=file_id,
                title=title,
                mime_type=mime_type,
                raw=raw,
                text=text,
                metadata=metadata,
                export_mime_type="text/plain",
            )
        if mime_type in TEXT_MIME_TYPES:
            raw = self.download_file(file_id)
            if mime_type == "application/rtf":
                suffix = ".rtf"
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"attachment{suffix}"
                    path.write_bytes(raw)
                    text, _details = extract_document_text(path)
            elif mime_type == "text/html":
                text = html_to_text(raw)
            else:
                text = raw.decode("utf-8", errors="ignore")
            return self._text_attachment(file_id=file_id, title=title, mime_type=mime_type, raw=raw, text=text, metadata=metadata)
        if mime_type in DOCUMENT_MIME_SUFFIXES:
            raw = self.download_file(file_id)
            suffix = DOCUMENT_MIME_SUFFIXES[mime_type]
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"attachment{suffix}"
                path.write_bytes(raw)
                text, details = extract_document_text(path)
            if not text.strip():
                return self._blocked(
                    file_id=file_id,
                    title=title,
                    mime_type=mime_type,
                    blocker="no_extractable_text",
                )
            attachment = self._text_attachment(file_id=file_id, title=title, mime_type=mime_type, raw=raw, text=text, metadata=metadata)
            attachment["extraction_details"] = details
            return attachment
        guessed = mimetypes.guess_extension(mime_type) if mime_type else ""
        return self._blocked(
            file_id=file_id,
            title=title,
            mime_type=mime_type,
            blocker="unsupported_attachment_type" if guessed != ".txt" else "no_extractable_text",
        )

    def resolve_classroom_attachment(self, raw: dict) -> dict:
        raw = raw or {}
        if raw.get("driveFile"):
            drive = raw.get("driveFile", {})
            file_obj = drive.get("driveFile", {}) if isinstance(drive.get("driveFile"), dict) else drive
            file_id = str(file_obj.get("id", "") or "").strip()
            title = str(file_obj.get("title", "") or file_obj.get("name", "") or "Drive attachment")
            try:
                return self.resolve_drive_file(file_id, fallback_title=title)
            except GoogleDriveError as exc:
                return self._blocked(file_id=file_id, title=title, blocker=exc.code)
        if raw.get("link"):
            link = raw.get("link", {}) if isinstance(raw.get("link"), dict) else {}
            return self._blocked(title=str(link.get("title", "") or link.get("url", "") or "External link"), blocker="external_link_unsupported", attachment_type="external_link")
        if raw.get("form"):
            form = raw.get("form", {}) if isinstance(raw.get("form"), dict) else {}
            return self._blocked(title=str(form.get("title", "") or "Google Form"), mime_type="application/vnd.google-apps.form", blocker="forms_unsupported")
        if raw.get("youTubeVideo"):
            video = raw.get("youTubeVideo", {}) if isinstance(raw.get("youTubeVideo"), dict) else {}
            return self._blocked(title=str(video.get("title", "") or "YouTube video"), blocker="youtube_unsupported")
        return self._blocked(title="Attachment", blocker="empty_attachment")

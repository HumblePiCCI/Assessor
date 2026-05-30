#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote

import httpx

from server.google_drive_adapter import GoogleDriveAdapter


CLASSROOM_API_BASE = "https://classroom.googleapis.com/v1"


class GoogleClassroomError(ValueError):
    def __init__(self, message: str, *, code: str = "classroom_api_error", status_code: int = 0, reason: str = ""):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.reason = reason


class ClassroomTransport:
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


def _google_error_detail(response: Any) -> tuple[str, str]:
    payload = _response_json(response)
    error = payload.get("error", {}) if isinstance(payload.get("error"), dict) else {}
    message = str(error.get("message", "") or payload.get("error_description", "") or payload.get("error", "") or "")
    reason = ""
    errors = error.get("errors", []) if isinstance(error.get("errors"), list) else []
    if errors and isinstance(errors[0], dict):
        reason = str(errors[0].get("reason", "") or errors[0].get("domain", "") or "")
    details = error.get("details", []) if isinstance(error.get("details"), list) else []
    for item in details:
        if isinstance(item, dict) and item.get("reason"):
            reason = str(item.get("reason", "") or reason)
            break
    return reason, message


def map_google_classroom_error(response: Any) -> str:
    status = _status_code(response)
    reason, message = _google_error_detail(response)
    combined = f"{reason} {message}".lower()
    if status == 401:
        return "missing_oauth_grant"
    if status == 403 and ("insufficient" in combined or "scope" in combined):
        return "insufficient_scope"
    if status == 403 and ("accessnotconfigured" in combined or "api has not been used" in combined or "disabled" in combined):
        return "classroom_api_disabled"
    if status == 403 and ("admin" in combined or "app blocked" in combined or "access blocked" in combined):
        return "admin_approval_required"
    if status == 403:
        return "admin_blocked_app"
    if status == 404:
        return "resource_not_found"
    if status in {429, 500, 503} or "quota" in combined or "rate limit" in combined or "ratelimit" in combined:
        return "quota_exhausted"
    return "classroom_api_error"


def _profile_name(profile: dict, fallback: str) -> str:
    name = profile.get("name", {}) if isinstance(profile.get("name"), dict) else {}
    return str(name.get("fullName", "") or profile.get("emailAddress", "") or profile.get("id", "") or fallback).strip()


def _submission_state(raw_state: str) -> str:
    state = str(raw_state or "").strip().upper()
    if state == "TURNED_IN":
        return "submitted"
    if state == "RETURNED":
        return "returned"
    if state == "RECLAIMED_BY_STUDENT":
        return "reclaimed"
    if state in {"NEW", "CREATED"}:
        return "missing"
    return state.lower() or "missing"


class GoogleClassroomAdapter:
    def __init__(
        self,
        access_token: str,
        *,
        classroom_transport: ClassroomTransport | None = None,
        drive_adapter: GoogleDriveAdapter | None = None,
    ):
        self.access_token = str(access_token or "")
        self.transport = classroom_transport or ClassroomTransport()
        self.drive_adapter = drive_adapter or GoogleDriveAdapter(access_token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, *, params: dict | None = None) -> dict:
        url = f"{CLASSROOM_API_BASE}{path}"
        response = self.transport.request(method, url, headers=self._headers(), params=params, timeout=30.0)
        if _status_code(response) >= 400:
            code = map_google_classroom_error(response)
            reason, message = _google_error_detail(response)
            raise GoogleClassroomError(
                message or f"Google Classroom API error: {code}",
                code=code,
                status_code=_status_code(response),
                reason=reason,
            )
        return _response_json(response)

    def _list_paginated(self, path: str, result_key: str, *, params: dict | None = None) -> list[dict]:
        rows: list[dict] = []
        page_token = ""
        while True:
            page_params = dict(params or {})
            if page_token:
                page_params["pageToken"] = page_token
            payload = self._request("GET", path, params=page_params)
            rows.extend(item for item in payload.get(result_key, []) or [] if isinstance(item, dict))
            page_token = str(payload.get("nextPageToken", "") or "")
            if not page_token:
                break
        return rows

    def list_courses(self) -> list[dict]:
        courses = self._list_paginated(
            "/courses",
            "courses",
            params={
                "teacherId": "me",
                "courseStates": ["ACTIVE"],
                "pageSize": 100,
            },
        )
        result = []
        for course in courses:
            result.append(
                {
                    "course_id": str(course.get("id", "") or ""),
                    "course_name": str(course.get("name", "") or course.get("section", "") or course.get("id", "") or ""),
                    "section": str(course.get("section", "") or ""),
                    "room": str(course.get("room", "") or ""),
                    "course_state": str(course.get("courseState", "") or ""),
                    "update_time": str(course.get("updateTime", "") or ""),
                }
            )
        return result

    def list_coursework(self, course_id: str, *, include_drafts: bool = False) -> list[dict]:
        states = ["PUBLISHED", "DRAFT"] if include_drafts else ["PUBLISHED"]
        rows = self._list_paginated(
            f"/courses/{quote(str(course_id), safe='')}/courseWork",
            "courseWork",
            params={
                "courseWorkStates": states,
                "pageSize": 100,
            },
        )
        allowed_states = {state.upper() for state in states}
        return [
            {
                "course_id": str(row.get("courseId", "") or course_id),
                "coursework_id": str(row.get("id", "") or ""),
                "coursework_title": str(row.get("title", "") or row.get("id", "") or ""),
                "coursework_state": str(row.get("state", "") or ""),
                "work_type": str(row.get("workType", "") or ""),
                "update_time": str(row.get("updateTime", "") or ""),
                "creation_time": str(row.get("creationTime", "") or ""),
                "due_date": row.get("dueDate", {}) if isinstance(row.get("dueDate"), dict) else {},
            }
            for row in rows
            if str(row.get("state", "") or "").upper() in allowed_states
        ]

    def get_coursework(self, course_id: str, coursework_id: str) -> dict:
        payload = self._request(
            "GET",
            f"/courses/{quote(str(course_id), safe='')}/courseWork/{quote(str(coursework_id), safe='')}",
        )
        return {
            "course_id": str(payload.get("courseId", "") or course_id),
            "coursework_id": str(payload.get("id", "") or coursework_id),
            "coursework_title": str(payload.get("title", "") or coursework_id),
            "coursework_state": str(payload.get("state", "") or ""),
            "work_type": str(payload.get("workType", "") or ""),
            "update_time": str(payload.get("updateTime", "") or ""),
            "creation_time": str(payload.get("creationTime", "") or ""),
            "due_date": payload.get("dueDate", {}) if isinstance(payload.get("dueDate"), dict) else {},
        }

    def list_roster(self, course_id: str) -> list[dict]:
        rows = self._list_paginated(
            f"/courses/{quote(str(course_id), safe='')}/students",
            "students",
            params={"pageSize": 100},
        )
        roster = []
        for row in rows:
            profile = row.get("profile", {}) if isinstance(row.get("profile"), dict) else {}
            user_id = str(row.get("userId", "") or profile.get("id", "") or "")
            roster.append(
                {
                    "student_id": user_id,
                    "display_name": _profile_name(profile, user_id),
                    "course_role": "student",
                    "classroom_user_id": user_id,
                }
            )
        return roster

    def list_submissions(self, course_id: str, coursework_id: str) -> list[dict]:
        rows = self._list_paginated(
            f"/courses/{quote(str(course_id), safe='')}/courseWork/{quote(str(coursework_id), safe='')}/studentSubmissions",
            "studentSubmissions",
            params={"pageSize": 100},
        )
        submissions = []
        for row in rows:
            raw_state = str(row.get("state", "") or "")
            attachments = []
            assignment = row.get("assignmentSubmission", {}) if isinstance(row.get("assignmentSubmission"), dict) else {}
            for attachment in assignment.get("attachments", []) or []:
                if not isinstance(attachment, dict):
                    continue
                attachments.append(self.drive_adapter.resolve_classroom_attachment(attachment))
            submission_id = str(row.get("id", "") or canonical_hash(row)[:24])
            user_id = str(row.get("userId", "") or "")
            submissions.append(
                {
                    "submission_id": submission_id,
                    "student_id": user_id,
                    "display_name": user_id,
                    "classroom_state": _submission_state(raw_state),
                    "google_submission_state": raw_state,
                    "submitted_at": str(row.get("creationTime", "") or ""),
                    "updated_at": str(row.get("updateTime", "") or ""),
                    "source_revision_id": canonical_hash(
                        {
                            "id": submission_id,
                            "updateTime": row.get("updateTime", ""),
                            "state": raw_state,
                            "attachments": [
                                {
                                    "attachment_id": attachment.get("attachment_id", ""),
                                    "file_hash": attachment.get("file_hash", ""),
                                    "text_hash": attachment.get("text_hash", ""),
                                    "blockers": attachment.get("blockers", []),
                                }
                                for attachment in attachments
                            ],
                        }
                    )[:24],
                    "attachments": attachments,
                }
            )
        return submissions

    def read_snapshot(self, course_id: str, coursework_id: str, *, course_name: str = "", coursework_title: str = "") -> dict:
        coursework = self.get_coursework(course_id, coursework_id)
        if str(coursework.get("coursework_state", "") or "").upper() == "ARCHIVED":
            raise GoogleClassroomError("Coursework is archived.", code="course_archived")
        roster = self.list_roster(course_id)
        roster_by_id = {str(item.get("student_id", "") or ""): item for item in roster}
        submissions = self.list_submissions(course_id, coursework_id)
        for submission in submissions:
            student = roster_by_id.get(str(submission.get("student_id", "") or ""), {})
            if student.get("display_name"):
                submission["display_name"] = student["display_name"]
        return {
            "adapter": "live_google",
            "course_id": str(course_id),
            "course_name": course_name or str(coursework.get("course_name", "") or course_id),
            "coursework_id": str(coursework_id),
            "coursework_title": coursework_title or str(coursework.get("coursework_title", "") or coursework_id),
            "coursework": coursework,
            "roster": roster,
            "submissions": submissions,
        }

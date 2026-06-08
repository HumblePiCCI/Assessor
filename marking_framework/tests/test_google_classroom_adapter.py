from server.google_classroom_adapter import GoogleClassroomAdapter, GoogleClassroomError


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class Transport:
    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append({"method": method, "url": url, "params": params or {}})
        route = self.routes.pop(0)
        assert route["path"] in url
        return Response(route.get("status", 200), route.get("payload", {}))


class Drive:
    def resolve_classroom_attachment(self, attachment):
        if attachment.get("link"):
            return {"attachment_id": "link", "type": "external_link", "blockers": ["external_link_unsupported"], "text": ""}
        return {"attachment_id": "doc", "mime_type": "text/plain", "type": "drive_file", "text": "Essay text.", "blockers": [], "text_hash": "text-hash", "file_hash": "file-hash"}


def test_classroom_adapter_paginates_courses_coursework_roster_and_submissions():
    transport = Transport(
        [
            {"path": "/courses", "payload": {"courses": [{"id": "c1", "name": "Period 2", "courseState": "ACTIVE"}], "nextPageToken": "n"}},
            {"path": "/courses", "payload": {"courses": [{"id": "c2", "name": "Period 3", "courseState": "ACTIVE"}]}},
            {"path": "/courseWork", "payload": {"courseWork": [{"id": "cw1", "courseId": "c1", "title": "Essay", "state": "PUBLISHED"}], "nextPageToken": "n"}},
            {"path": "/courseWork", "payload": {"courseWork": []}},
            {"path": "/courseWork/cw1", "payload": {"id": "cw1", "courseId": "c1", "title": "Essay", "state": "PUBLISHED"}},
            {"path": "/students", "payload": {"students": [{"userId": "u1", "profile": {"id": "u1", "name": {"fullName": "Student One"}}}]}},
            {
                "path": "/studentSubmissions",
                "payload": {
                    "studentSubmissions": [
                        {"id": "s1", "userId": "u1", "state": "TURNED_IN", "assignmentSubmission": {"attachments": [{"driveFile": {"driveFile": {"id": "file-1", "title": "Essay"}}}]}},
                        {"id": "s2", "userId": "u2", "state": "RECLAIMED_BY_STUDENT", "assignmentSubmission": {"attachments": [{"link": {"url": "https://example.com"}}]}},
                        {"id": "s3", "userId": "u3", "state": "RETURNED", "assignmentSubmission": {"attachments": []}},
                        {"id": "s4", "userId": "u4", "state": "CREATED", "assignmentSubmission": {"attachments": []}},
                    ]
                },
            },
        ]
    )
    adapter = GoogleClassroomAdapter("token", classroom_transport=transport, drive_adapter=Drive())
    assert [row["course_id"] for row in adapter.list_courses()] == ["c1", "c2"]
    assert [row["coursework_id"] for row in adapter.list_coursework("c1")] == ["cw1"]
    assert transport.calls[2]["params"]["courseWorkStates"] == ["PUBLISHED"]
    snapshot = adapter.read_snapshot("c1", "cw1")
    assert snapshot["adapter"] == "live_google"
    assert snapshot["roster"][0]["display_name"] == "Student One"
    states = {row["submission_id"]: row["classroom_state"] for row in snapshot["submissions"]}
    assert states == {"s1": "submitted", "s2": "reclaimed", "s3": "returned", "s4": "missing"}
    assert snapshot["submissions"][0]["attachments"][0]["attachment_id"] == "doc"


def test_classroom_adapter_can_include_drafts_only_when_explicit():
    transport = Transport(
        [
            {
                "path": "/courseWork",
                "payload": {
                    "courseWork": [
                        {"id": "cw1", "courseId": "c1", "title": "Essay", "state": "PUBLISHED"},
                        {"id": "cw2", "courseId": "c1", "title": "Draft", "state": "DRAFT"},
                    ]
                },
            }
        ]
    )
    rows = GoogleClassroomAdapter("token", classroom_transport=transport, drive_adapter=Drive()).list_coursework("c1", include_drafts=True)
    assert [row["coursework_id"] for row in rows] == ["cw1", "cw2"]
    assert transport.calls[0]["params"]["courseWorkStates"] == ["PUBLISHED", "DRAFT"]


def test_classroom_adapter_maps_api_errors_to_product_codes():
    transport = Transport(
        [
            {
                "path": "/courses",
                "status": 403,
                "payload": {"error": {"message": "Request had insufficient authentication scopes.", "errors": [{"reason": "insufficientPermissions"}]}},
            }
        ]
    )
    adapter = GoogleClassroomAdapter("token", classroom_transport=transport, drive_adapter=Drive())
    try:
        adapter.list_courses()
    except GoogleClassroomError as exc:
        assert exc.code == "insufficient_scope"
    else:
        raise AssertionError("insufficient scope should fail closed")

    quota = Transport([{"path": "/courses", "status": 429, "payload": {"error": {"message": "quota exceeded"}}}])
    try:
        GoogleClassroomAdapter("token", classroom_transport=quota, drive_adapter=Drive()).list_courses()
    except GoogleClassroomError as exc:
        assert exc.code == "quota_exhausted"
    else:
        raise AssertionError("quota failure should map to blocker")

    unavailable = Transport([{"path": "/courses", "status": 503, "payload": {"error": {"message": "backend unavailable"}}}])
    try:
        GoogleClassroomAdapter("token", classroom_transport=unavailable, drive_adapter=Drive()).list_courses()
    except GoogleClassroomError as exc:
        assert exc.code == "google_api_unavailable"
    else:
        raise AssertionError("service failures should map to unavailable blocker")

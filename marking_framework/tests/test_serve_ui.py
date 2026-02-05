import io
import json
import types
from pathlib import Path

import scripts.serve_ui as su


def test_serve_ui_missing_ui(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["su", "--ui", str(tmp_path / "missing"), "--data", str(tmp_path / "data.json")])
    assert su.main() == 1


def test_serve_ui_missing_data(tmp_path, monkeypatch):
    ui = tmp_path / "ui"
    ui.mkdir()
    class DummyServer:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def serve_forever(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(su.socketserver, "TCPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("sys.argv", ["su", "--ui", str(ui), "--data", str(tmp_path / "missing.json")])
    assert su.main() == 0


def test_serve_ui_success(tmp_path, monkeypatch):
    ui = tmp_path / "ui"
    ui.mkdir()
    data = tmp_path / "data.json"
    data.write_text("{}", encoding="utf-8")

    class DummyServer:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def serve_forever(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(su.socketserver, "TCPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("sys.argv", ["su", "--ui", str(ui), "--data", str(data), "--port", "9999"])
    assert su.main() == 0


def test_load_data_payload(tmp_path):
    status, content = su.load_data_payload(tmp_path / "missing.json")
    assert status == 200
    assert json.loads(content) == {"students": []}
    data = tmp_path / "data.json"
    data.write_text("{}", encoding="utf-8")
    status2, content2 = su.load_data_payload(data)
    assert status2 == 200
    assert content2 == "{}"


def make_handler(path: str, ui_dir: Path, data_path: Path):
    request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode("utf-8")

    class DummySocket:
        def __init__(self, payload):
            self._rfile = io.BytesIO(payload)
            self._wfile = io.BytesIO()
        def makefile(self, mode, *args, **kwargs):
            if "r" in mode:
                return self._rfile
            return self._wfile
        def sendall(self, data):
            self._wfile.write(data)

    class DummyServer:
        server_version = "Test"
        sys_version = ""
        server_address = ("127.0.0.1", 0)

    sock = DummySocket(request)
    handler = su.DashboardHandler(sock, ("127.0.0.1", 12345), DummyServer(), ui_dir=ui_dir, data_path=data_path)
    return handler, sock


def test_dashboard_handler_data_json(tmp_path):
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    data = tmp_path / "data.json"
    data.write_text("{}", encoding="utf-8")
    handler, sock = make_handler("/data.json", ui_dir, data)
    sock.makefile("wb")
    content = sock._wfile.getvalue().decode("utf-8")
    assert "200" in content


def test_dashboard_handler_data_missing(tmp_path):
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    missing = tmp_path / "missing.json"
    handler, sock = make_handler("/data.json", ui_dir, missing)
    sock.makefile("wb")
    content = sock._wfile.getvalue().decode("utf-8")
    assert "200" in content


def test_dashboard_handler_non_data_path(tmp_path, monkeypatch):
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    data = tmp_path / "data.json"
    data.write_text("{}", encoding="utf-8")
    called = {"ok": False}

    def fake_do_get(self):
        called["ok"] = True

    monkeypatch.setattr(su.http.server.SimpleHTTPRequestHandler, "do_GET", fake_do_get)
    handler, sock = make_handler("/", ui_dir, data)
    assert called["ok"] is True

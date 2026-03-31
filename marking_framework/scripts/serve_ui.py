#!/usr/bin/env python3
import argparse
import http.server
import json
import socketserver
from pathlib import Path


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, ui_dir=None, data_path=None, **kwargs):
        self.ui_dir = ui_dir
        self.data_path = data_path
        super().__init__(*args, directory=str(ui_dir), **kwargs)

    def do_GET(self):
        if self.path == "/data.json":
            status, content = load_data_payload(self.data_path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            return
        return super().do_GET()


def load_data_payload(data_path: Path):
    if data_path and data_path.exists():
        return 200, data_path.read_text(encoding="utf-8")
    return 200, '{"students": []}'


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the teacher review UI")
    parser.add_argument("--ui", default="ui", help="UI directory")
    parser.add_argument("--data", default="outputs/dashboard_data.json", help="Dashboard data JSON")
    parser.add_argument("--port", type=int, default=7860, help="Port to serve on")
    args = parser.parse_args()

    ui_dir = Path(args.ui)
    data_path = Path(args.data)
    if not ui_dir.exists():
        print(f"Error: UI directory not found: {ui_dir}")
        return 1
    if not data_path.exists():
        print(f"Warning: Data file not found: {data_path}")
        print("Run: python3 scripts/build_dashboard_data.py")

    handler = lambda *h_args, **h_kwargs: DashboardHandler(
        *h_args, ui_dir=ui_dir, data_path=data_path, **h_kwargs
    )

    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Serving UI at http://localhost:{args.port}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

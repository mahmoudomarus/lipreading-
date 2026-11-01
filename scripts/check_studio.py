"""Check authenticated Studio endpoints with a user-supplied synthetic fixture."""

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--server", default="http://127.0.0.1:8765")
p.add_argument("--fixture", type=Path, help="Optional short WebM/MP4 test recording to convert")
p.add_argument("--site-origin", help="Optional separately hosted frontend origin for CORS")
args = p.parse_args()
token = (ROOT / ".runtime/access-token").read_text().strip()


def request(path, method="GET", data=None, content_type=None):
    headers = {"Authorization": "Bearer " + token}
    if args.site_origin:
        headers["Origin"] = args.site_origin
    if content_type:
        headers["Content-Type"] = content_type
    return urllib.request.urlopen(
        urllib.request.Request(
            args.server.rstrip("/") + path, method=method, data=data, headers=headers
        ),
        timeout=75,
    )


status = json.load(request("/api/status"))
print("Service:", status["status"])
config = json.load(request("/api/provider/config"))
print("Text provider configured:", config["configured"])
if args.fixture:
    response = request("/api/export", "POST", args.fixture.read_bytes(), "application/octet-stream")
    data = response.read()
    assert response.headers["Content-Type"].startswith("video/mp4") and b"ftyp" in data[:40]
    if args.site_origin:
        assert response.headers["Access-Control-Allow-Origin"] == args.site_origin
    (ROOT / ".runtime/export-http-test.mp4").write_bytes(data)
    print("MP4 conversion verified:", len(data), "bytes")

"""Create a private phone link and QR for an already running tunnel."""

import argparse
import os
from pathlib import Path
from urllib.parse import urlencode, urlparse

import qrcode

parser = argparse.ArgumentParser()
parser.add_argument("origin")
parser.add_argument("--site-url")
args = parser.parse_args()
origin = urlparse(args.origin)
if origin.scheme != "https" or not origin.netloc:
    parser.error("An HTTPS tunnel origin is required")
runtime = Path(__file__).resolve().parents[1] / ".runtime"
token = (runtime / "access-token").read_text().strip()
if args.site_url:
    site = urlparse(args.site_url)
    if site.scheme != "https" or not site.netloc:
        parser.error("A secure Site URL is required")
    url = f"https://{site.netloc}/#" + urlencode(
        {"server": f"https://{origin.netloc}", "key": token}
    )
    name = "site"
else:
    url = f"https://{origin.netloc}/#" + urlencode({"key": token})
    name = "phone"
(runtime / (name + "-url")).write_text(url)
os.chmod(runtime / (name + "-url"), 0o600)
qrcode.make(url).save(runtime / (name + "-qr.png"))
print(url)

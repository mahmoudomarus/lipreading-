"""Start the model server and temporary HTTPS tunnel; print a phone link and QR."""

import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
runtime = ROOT / ".runtime"
runtime.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(runtime / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(runtime / "cache"))
children = []


def stop(*args):
    for process in reversed(children):
        process.terminate()
    for process in children:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    sys.exit(0)


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
log = open(runtime / "server.log", "a")
server = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--ws-max-size",
        "300000",
        "--ws-max-queue",
        "8",
        "--no-access-log",
    ],
    stdout=log,
    stderr=log,
)
children.append(server)
import time
import urllib.request

for _ in range(60):
    if server.poll() is not None:
        sys.exit("Server did not start. Check .runtime/server.log (or stop the existing server).")
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/", timeout=2)
        break
    except OSError:
        time.sleep(0.5)
else:
    stop()

tunnel = subprocess.Popen(
    [
        "cloudflared",
        "tunnel",
        "--url",
        "http://127.0.0.1:8765",
        "--no-autoupdate",
        "--protocol",
        "http2",
    ],
    stderr=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    text=True,
)
children.append(tunnel)
try:
    for line in tunnel.stderr:
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if match:
            origin = match.group()
            token = (runtime / "access-token").read_text().strip()
            url = origin + "/#" + urlencode({"key": token})
            (runtime / "phone-url").write_text(url)
            os.chmod(runtime / "phone-url", 0o600)
            if (runtime / "site-origin").exists():
                site = (runtime / "site-origin").read_text().strip()
                (runtime / "site-url").write_text(
                    site.rstrip("/") + "/#" + urlencode({"server": origin, "key": token})
                )
                os.chmod(runtime / "site-url", 0o600)
            import qrcode

            qr = qrcode.QRCode(border=2)
            qr.add_data(url)
            qr.make(fit=True)
            qr.make_image().save(runtime / "phone-qr.png")
            print("\nOpen on your phone:\n" + url + "\n", flush=True)
            qr.print_ascii(invert=True)
            print(
                "Keep this terminal and computer running. Ctrl+C stops the camera service.\n"
                "Model startup may take about a minute. Logs: .runtime/server.log",
                flush=True,
            )
            # Keep draining logs so the tunnel cannot block on a full pipe.
    stop()
except (KeyboardInterrupt, Exception):
    stop()

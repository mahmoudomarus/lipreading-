"""Start the model server and temporary HTTPS tunnel; print a phone link and QR."""

import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]


def write_computer_link(runtime):
    token = (runtime / "access-token").read_text().strip()
    url = "http://127.0.0.1:8765/#" + urlencode({"key": token})
    path = runtime / "computer-url"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(url)
    os.chmod(path, 0o600)
    return url


def wait_for_server(server, *, attempts=60, opener=None, sleep=time.sleep):
    opener = opener or urllib.request.urlopen
    for _ in range(attempts):
        if server.poll() is not None:
            raise RuntimeError(
                "Server did not start. Check .runtime/server.log (or stop the existing server)."
            )
        try:
            with opener("http://127.0.0.1:8765/", timeout=2):
                return
        except OSError:
            sleep(0.5)
    raise RuntimeError("Server startup timed out. Check .runtime/server.log.")


def main():
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(runtime / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(runtime / "cache"))
    children = []

    def stop(*args, exit_code=0):
        for process in reversed(children):
            process.terminate()
        for process in children:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        sys.exit(exit_code)

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
        cwd=ROOT,
    )
    children.append(server)

    try:
        wait_for_server(server)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        stop(exit_code=1)

    print("\nOpen on this computer:\n" + write_computer_link(runtime) + "\n", flush=True)
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
            log.write(line)
            log.flush()
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
        stop(exit_code=1)
    except KeyboardInterrupt:
        stop()
    except Exception:
        stop(exit_code=1)


if __name__ == "__main__":
    main()

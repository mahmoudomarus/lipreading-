"""Run the phone service detached from the terminal, with explicit start/status/stop."""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
PID = RUNTIME / "service.pid"
COMMAND = str(ROOT / "scripts/serve.py")


def running():
    try:
        pid = int(PID.read_text())
        command = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="], text=True
        ).strip()
        return pid if COMMAND in command else None
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=["start", "status", "stop", "restart"])
    args = p.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    pid = running()
    if args.operation == "restart":
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not running():
                    break
                time.sleep(0.1)
            if running():
                sys.exit("The previous service is still stopping. Try again shortly.")
        pid = None
        args.operation = "start"
    if args.operation == "start":
        if pid:
            print("Service already running:", pid)
            return
        # Avoid orphaning a second tunnel if an independently started server owns the port.
        import socket

        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", 8765)) == 0:
                sys.exit("Port 8765 is already in use. Stop the existing lip-reading server first.")
        fd = os.open(RUNTIME / "service.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as log:
            child = subprocess.Popen(
                [sys.executable, COMMAND],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        PID.write_text(str(child.pid))
        os.chmod(PID, 0o600)
        time.sleep(1)
        if child.poll() is not None:
            sys.exit("Service failed. See .runtime/service.log.")
        print("Background service started:", child.pid)
        print("Phone link: .runtime/phone-url (wait for the tunnel). Computer must stay awake.")
    elif args.operation == "stop":
        if not pid:
            print("Service is not running.")
            return
        os.kill(pid, signal.SIGTERM)
        print("Stop requested for lip-reading service:", pid)
    else:
        print("Running: " + str(pid) if pid else "Not running through this service manager.")


if __name__ == "__main__":
    main()

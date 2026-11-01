"""Build an allowlisted source archive; omit credentials, hosting identity and local data."""

import hashlib
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ".gitignore",
    ".env.example",
    "LICENSE",
    "THIRD_PARTY.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "assets.json",
    "requirements.txt",
    "requirements-test.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "engine.py",
    "recognition_guard.py",
    "turn_taking.py",
    "web_results.py",
    "server.py",
    "provider.py",
    "agent.py",
    "openai_bridge.py",
    "video_export.py",
    "phone-app/package.json",
    "phone-app/package-lock.json",
    "phone-app/.prettierrc.json",
]
for folder, patterns in [
    ("scripts", ["*.py"]),
    ("tests", ["*.py"]),
    ("docs", ["*.md", "examples/*.jsonl"]),
    ("phone-app/dist", ["*.html", "*.js", "*.css", "*.svg"]),
    ("phone-app/tests", ["*.mjs"]),
    (".github", ["**/*.yml", "**/*.md"]),
]:
    for pattern in patterns:
        FILES.extend(str(p.relative_to(ROOT)) for p in (ROOT / folder).glob(pattern) if p.is_file())
output = ROOT / "outputs/lipread-lab-source.tar.gz"
output.parent.mkdir(exist_ok=True)
private_values = [os.environ.get(n, "").encode() for n in ("AGENT_API_KEY", "OPENAI_API_KEY")]
if (ROOT / ".runtime/access-token").exists():
    private_values.append((ROOT / ".runtime/access-token").read_bytes().strip())
for name in FILES:
    data = (ROOT / name).read_bytes()
    if any(secret and secret in data for secret in private_values):
        raise SystemExit("Private value detected; archive not created.")
with tarfile.open(output, "w:gz") as archive:
    for name in sorted(set(FILES)):
        archive.add(ROOT / name, arcname="lipread-lab/" + name, recursive=False)
print(output)
print("Files:", len(set(FILES)))
print("SHA256:", hashlib.sha256(output.read_bytes()).hexdigest())

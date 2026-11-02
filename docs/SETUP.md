# Setup and first use

## Requirements and support

| Item | Why it is needed |
| --- | --- |
| Python 3.11 | The development Python version; start with a clean virtual environment |
| Git | Clone this repository and fetch the pinned Chaplin inference code |
| cloudflared | Temporary HTTPS tunnel so your phone can request camera access |
| Node 22 | Frontend tests only; no Node service or npm install is needed for normal use |
| Several GB of storage | Approximately 1.25 GB of model assets plus PyTorch and other dependencies |

The full app was developed on macOS. CPU recognition is the default; Metal acceleration is experimental. CI exercises protocol/agent/export/UI helper tests on Linux without weights. Full Linux inference, NVIDIA acceleration, Windows, and specific phone/browser combinations need contributors to validate them. The detached service manager uses Unix process tools; it is not a Windows service.

On a Mac with Homebrew installed:

```sh
brew install python@3.11 git cloudflared
```

Use the official [Python](https://www.python.org/downloads/), [PyTorch](https://pytorch.org/get-started/locally/), and [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installation instructions for your platform. Install a matching `torch`, `torchvision`, and `torchaudio` set if you choose platform-specific PyTorch builds. Development used 2.11.0 / 0.26.0 / 2.11.0; the dependency ranges are not a cross-platform lockfile.

## Install

```sh
git clone https://github.com/mahmoudomarus/lipreading-.git
cd lipreading-
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup.py
.venv/bin/python scripts/doctor.py
```

`setup.py` clones the vendor revision from `assets.json` and verifies the byte count and SHA256 of each downloaded model. A wrong or interrupted download is not accepted. Existing mismatched assets require `--repair`; replacements are verified before the old file is replaced. A modified vendor checkout is preserved and reported, not silently reset.

```sh
.venv/bin/python scripts/setup.py --verify-only
# Only if an asset mismatch needs replacement:
.venv/bin/python scripts/setup.py --repair
```

Asset URLs are upstream download locations. The checksums record the development assets even if an upstream `main`/`latest` URL changes. If that happens, verify provenance and model terms before updating the manifest; do not simply disable verification. See [third-party notices](../THIRD_PARTY.md). Weights and training data are not included in Git.

## Start and connect a phone

```sh
.venv/bin/python scripts/serve.py
```

The service binds to `127.0.0.1:8765`. It first prints a private computer link, saved in `.runtime/computer-url`, for direct desktop-camera testing. It also starts a temporary HTTPS tunnel and prints a separate private phone link and QR code. Use the computer link on the host machine to avoid routing camera video through the tunnel. Model loading continues in the background. Wait until the page says it is ready, then allow camera access. Use Safari or Chrome, keep the page visible, face the lens in good light, and speak a short phrase naturally. **Live replies** is on by default: finalized predictions go to the agent as you pause. **Finish sentence** is a fallback when a pause is missed. Switch Live replies off for manual review. Notes and timers still wait for action confirmation. With the face-landmarker asset installed, sustained lip movement starts a turn and a visual pause ends it; continue speaking while background tasks keep running; lip movement only silences generated audio. See [turn-taking](TURN_TAKING.md).

The link contains the app's access token in its fragment. Treat it as a password. It is different from a model-provider API key. Links are stripped from the address bar after connection; the connection is kept in browser session storage. Tunnel origins change when restarted. A static preview alone cannot run inference: the computer service is required.

## Bring a text model

Recognition works without a text provider. The agent needs a model that follows the structured action instructions. In Settings choose **Responses** or **Chat-compatible**, enter the provider's base URL and model ID, and supply a key if required. The server makes a small connection-check request, which may incur usage charges.

Example for an already installed local model:

```sh
export AGENT_PROTOCOL=chat
export AGENT_BASE_URL=http://127.0.0.1:11434/v1
export AGENT_MODEL=your-installed-model
.venv/bin/python scripts/serve.py
```

`localhost` refers to the computer running the Python service, not the phone. Local Ollama/LM Studio-style compatible endpoints can use this arrangement. Hosted compatible endpoints use HTTPS and normally need `AGENT_API_KEY`. Use the provider's current endpoint and model ID. The frontend is provider-neutral; the included adapters do not cover every proprietary protocol.

The complete setting table and local/hosted examples are maintained in [README section 6](../README.md#6-connect-a-text-model). `.env.example` is documentation rather than an automatically loaded file. Optional candidate assistance selects existing readings; optional speech uses the included text-only adapter.

## Background computer operation

```sh
.venv/bin/python scripts/service.py start
.venv/bin/python scripts/service.py status
.venv/bin/python scripts/service.py restart
.venv/bin/python scripts/service.py stop
```

Use either the foreground launcher or detached launcher, not both. The manager starts its own server/tunnel and writes PID, logs, and links in `.runtime/`. It does not install a login item, restart on system reboot, or prevent computer sleep. Restarting after changing environment variables loads the new process environment. A server restart marks in-flight model calls failed instead of replaying them; queued jobs resume and pending confirmations remain available.

Agent work can complete while the browser is closed. Timer due times persist and update after reconnecting, but there are no closed-phone push notifications or alarm sounds. Camera capture pauses when the page becomes hidden and resumes on return after its previous capture finishes. Stop reading keeps capture stopped. iOS does not support the locked/background camera experience this prototype would otherwise need.

## Separate frontend

The backend serves `phone-app/dist` directly, so separate frontend hosting is optional. To host those static assets elsewhere, set `LIPREAD_SITE_ORIGIN` to its exact origin before launching, then generate a connected link:

```sh
.venv/bin/python scripts/phone_link.py https://your-tunnel.example --site-url https://your-frontend.example
```

Use one uvicorn process/worker. Recognition and camera ownership are serialized. Production/multi-user deployment requires additional design and review. See [troubleshooting](TROUBLESHOOTING.md).

# Development

Read [architecture](ARCHITECTURE.md) before changing a recognition boundary, tool, or provider. Keep changes small and explain what user behavior changes.

## Lightweight checks

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
node --test phone-app/tests/*.test.mjs
```

Install FFmpeg first; conversion tests use synthetic recordings. Node 22 is the CI baseline. No npm install, GPU, camera, provider account, vendor checkout, or model weights are required. `.github/workflows/checks.yml` runs these checks. Real integration checks are intentionally not part of CI: they need credentials/hardware and can incur charges.

The frontend is maintained directly in `phone-app/dist`. Serve through `server.py` for the real authenticated app. A static server can preview markup but cannot perform recognition or agent actions. Localhost camera permissions and phone HTTPS access are different environments.

## Real integration and performance checks

With the full installation and running service:

```sh
# Actual configured text model; temporary test notes/timers are isolated and deleted.
.venv/bin/python scripts/check_agent.py
# Production HTTP path; creates and then removes only its own calculator test job.
.venv/bin/python scripts/check_harness_http.py http://127.0.0.1:8765
# Optional separate frontend origin:
.venv/bin/python scripts/check_harness_http.py https://your-tunnel.example --site-origin https://your-frontend.example
# Studio status and optional bounded synthetic video conversion:
.venv/bin/python scripts/check_studio.py --fixture path/to/synthetic.webm
# Actual camera protocol, ignoring any audio track in the supplied clip:
.venv/bin/python scripts/smoke_video.py path/to/consented-clip.mp4 --mode live
# Held-out references remain in this evaluator, never in recognizer requests:
.venv/bin/python scripts/evaluate.py path/to/heldout.jsonl --report .runtime/evaluation.json
# Development microprofiles, not accuracy benchmarks:
.venv/bin/python scripts/profile_cache.py path/to/consented-clip.mp4
.venv/bin/python scripts/benchmark.py path/to/consented-clip.mp4
```

The HTTP harness script assumes it runs from the same checkout/data store as the service so it can remove its own test job. Use it on a development instance. `scripts/check_openai.py --voice` exercises the optional legacy adapter explicitly and may incur charges; it is not needed for other text endpoints. No integration script should print a key or private phone link except the dedicated link/launcher tools.

## Manual device checks

Verify camera permission success/denial, front/rear switching, orientation changes, hidden-page capture stop, reconnect, caption replacement, automatic replies, switching Live replies off, duplicate-final deduplication, editing a request, pending action cancellation, repeated confirmation, reconnect after a completed job, timer elapsed state, Studio aspect ratio/recording/conversion, and optional speech mixing. Check that recorded media includes provenance labels and no settings/connection data. Record the device/browser and which checks passed.

## Release preparation

```sh
.venv/bin/python scripts/package_source.py
```

The allowlisted archive in `outputs/` omits runtime data, `.env`, model weights, vendor downloads, Git history, and hosting identity. Inspect staged filenames and scan for credentials before pushing. Keep the original MIT license and third-party notices. Do not copy a personal installation wholesale into a release.

## Formatting

Python uses Ruff 0.15.10 and frontend source uses the locked Prettier version. These are development-only dependencies:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff format agent.py engine.py provider.py server.py openai_bridge.py video_export.py scripts tests
npm --prefix phone-app ci
npm --prefix phone-app run format
```

CI checks formatting and tests. Use `format:check` or `ruff format --check` to verify without rewriting files. Runtime use still needs no npm installation.

# Architecture and extension points

## Repository map

```text
agent.py                  SQLite jobs, validated plans, local tools and receipts
provider.py               Generic Responses / Chat-compatible text adapter
engine.py                 Visual recognition, preprocessing and framing feedback
server.py                 Authenticated HTTP + camera WebSocket; static assets
openai_bridge.py          Optional legacy speech/candidate adapter
video_export.py           Bounded FFmpeg conversion with temporary-file cleanup
assets.json               Vendor revision and model asset hashes/sizes
phone-app/dist/           Buildless HTML, CSS and JavaScript source
phone-app/tests/          Node tests for pure helpers and UI bindings
scripts/                  Launchers, diagnostics, evaluations and source packaging
tests/                    Python unit and protocol tests; no weights needed
docs/                     Setup, research, architecture and contribution roadmap
```

`dist/` is the maintained frontend source in this small prototype, not a generated framework bundle. There is no npm build step. Model files, downloaded vendor code, local data, and `.env` files are ignored. No hosting account configuration is required for the public repository.

## Recognition pipeline

The phone requests video with `audio:false`, captures distinct sensor frames, encodes JPEGs up to 800 pixels on the long edge, and applies WebSocket backpressure. Binary packets consist of an 8-byte little-endian float64 capture timestamp in seconds followed by JPEG bytes. The first WebSocket message authenticates the session. Hostile sizes, unsupported image dimensions, slow delivery, and changed frame timing are rejected.

The server keeps a bounded utterance buffer, resamples to 25 FPS while preserving elapsed time, detects/alines a face using MediaPipe and the upstream cropper, and normalizes mouth crops for Auto-AVSR. Cached detections are scoped to the capture session. CNN/Conformer features and CTC drafts are recomputed for growing windows. Full decoding refines the phrase on manual finish, a heuristic pause, or the window limit. Finalized frames are consumed once; new frames arriving during inference are retained.

This is **windowed offline inference**, not a causal streaming model. Quality guidance measures framing, lighting, and motion. Neither it nor decoder alternatives are calibrated word confidence. Do not map similarity scores to a confidence percentage.

## Agent pipeline and contracts

`POST /api/agent/jobs` accepts a final-prediction, reviewed, or typed request plus a client UUID. It persists before responding; the asynchronous worker continues independently of the browser. The source is `lip_prediction` for automatic final camera turns, `reviewed_lips` for manual review, or `typed`. Frontend drafts are never submitted. Automatic turns are serialized and deduplicated per camera session/segment; retries retain their UUID. Live replies can be switched off. This source label is an application contract, not independent proof that recognition was correct.

State transitions:

```text
queued → thinking → completed                 # answer or read-only tools
                  → review → completed        # write tools, after confirmation
                           → cancelled
                  → failed
```

A server restart marks `thinking` failed. The same UUID with the same input returns the existing job; changed words with an existing UUID are rejected. A new user-approved retry uses a new UUID.

`provider.py` sends the request and a bounded recent completed conversation to the model. It returns a structured **proposal**, not permission to execute arbitrary code. `validate_plan` checks the tool allowlist, argument shapes/ranges, and action count. Writes wait for confirmation. SQLite commits each action and its receipt in the same transaction; repeated confirmation returns the same completed result. UI and Studio distinguish proposals from actual execution receipts.

The included tools are local and narrow. `calculate` evaluates a restricted arithmetic AST, never `eval`. There are no external write actions. Timer state consists of persisted due times; notification delivery is not implemented.

## HTTP surface

All `/api/` HTTP routes require `Authorization: Bearer <app-access-token>`. `/api/stream` checks the origin and authenticates in its first message. The public static root exposes no runtime files.

| Route | Purpose |
| --- | --- |
| `GET /api/status` | Model readiness and service capabilities |
| `WS /api/stream` | Camera frames, draft/result/quality events, commit/finish controls |
| `GET/POST/DELETE /api/provider/config` | Inspect/configure/disconnect a text provider without returning its key |
| `POST /api/provider/assist` | Select an existing visual candidate, never an invented replacement |
| `POST /api/provider/voice` | Optional supported speech adapter |
| `GET/POST /api/agent/jobs` | Poll recent jobs/timers or submit an automatic final prediction, reviewed request, or typed message |
| `POST /api/agent/jobs/{id}/confirm` | Execute a pending write proposal once |
| `POST /api/agent/jobs/{id}/cancel` | Cancel a queued job or pending proposal |
| `POST /api/export` | Convert a bounded browser recording to MP4 |

`/api/openai/*` routes remain for compatibility with the earlier private prototype. New UI/integrations should use the generic provider routes. API documentation is intentionally not served publicly; this prototype has no stable versioned external API promise yet.

## Where to extend

- **New recognizer:** preserve frame timing, draft/final boundaries, quality abstentions and real latency measurements. Replace the backend behind `LipReader` only after comparing held-out clips. A streaming implementation needs its own causal state and matching trained checkpoint.
- **New text protocol:** implement connection validation and `complete()` in `provider.py`. Keep keys server-side, never transfer old keys to a new endpoint, redact errors, and locally validate plans even if the provider advertises strict schemas.
- **New tool:** update the allowlist/schema, argument validation, transactional execution, UI labels, and tests together. External actions need a durable idempotency/reconciliation design; SQLite alone cannot make a remote API exactly-once.
- **New speech adapter:** separate it from silent recognition and preserve provenance labels. Do not silently fall back to microphone transcription.
- **Personalized commands:** build a separate opt-in data/calibration path. Preserve unknown/no-speech examples and an abstain outcome. Do not force arbitrary speech into the nearest known command.

The app is deliberately single-user and single-worker. Multi-user isolation, durable secret storage, external agent frameworks, and native background capture are future work, not existing capabilities.

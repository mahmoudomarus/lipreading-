# Architecture and extension points

## Components

| Responsibility | Module |
| --- | --- |
| App factory, HTTP, authentication, camera ownership | `server.py` |
| Startup and shutdown resources | `runtime.py` |
| Camera session state and scheduling | `stream_session.py` |
| Bounded consume-once video buffer | `stream_buffer.py` |
| Shared backend protocol and timing constants | `config.py` |
| Visual encoder, CTC, beam decoding and framing feedback | `engine.py` |
| Lip activity and utterance assembly | `turn_taking.py` |
| Existing abstention and repetition heuristics | `recognition_guard.py` |
| Structured text provider adapter | `provider.py` |
| Durable jobs, validated tools and receipts | `agent.py` |
| Cited report and public-link validation | `web_results.py` |
| Optional speech and compatibility adapter | `openai_bridge.py` |
| Recording conversion | `video_export.py` |
| Buildless browser application | `phone-app/dist/` |

`create_app(runtime_dir, load_models=...)` creates independent application state. Lifespan startup creates the app token, SQLite store, providers, locks and three single-thread executors. Importing `server` does not create a token, database or worker pools. Tests use temporary runtime directories and `load_models=False` with controlled recognition fixtures. Normal startup loads the pinned assets.

## Camera and recognition

```text
Phone video without audio
  -> timestamp plus JPEG over authenticated WebSocket
  -> single-session lock -> StreamSession -> bounded StreamBuffer
       -> framing executor -> QualityMonitor -> quality advice
       -> lip-activity executor -> MouthMonitor -> visual turn boundaries
       -> recognition executor, inference lock -> LipReader
            -> resample -> align mouth crops -> encoder -> greedy CTC draft
            -> attention/CTC/trained-LM beam -> best and alternatives
  -> Utterances -> final text, draft evidence and bounded alternatives
  -> existing guard decisions -> caption and eligible final request
```

The browser paces distinct frames toward 25 FPS, resizes to 800 pixels and applies backpressure. Packets contain an eight-byte little-endian float64 capture timestamp and JPEG bytes. The backend validates size, dimensions and timing. Finalized frames are consumed once while later frames remain buffered. Protocol version and draft timing come from `config.py`; HTTP status and the connected event use the same version.

The recognizer repeatedly processes offline windows. The advice thresholds for face size and head angle are stricter than rejection thresholds so the UI can suggest improvements before capture fails. [Recognition limitations](../README.md#limitations).

Single-part turns retain their native alternatives. Multi-part turns keep earlier best readings and substitute only alternatives from the last part, with at most two distinct full-turn alternatives. Drafts are joined only when every part supplied real draft text. A held part keeps the complete turn held. Manual comparison uses the existing text selector and is disabled when no distinct supported candidate exists. Automatic selection is not enabled on assembled visual turns.

## Agent state and execution

```text
queued -> thinking -> completed                 answer or read-only tools
                 -> researching -> completed   cited research
                 -> review -> completed         confirmed local writes
                           -> cancelled
queued -> cancelled
queued, thinking, researching, review -> interrupted
thinking, researching -> failed                 request failure or restart
any automatic lip job -> dismissed              excluded from future context
```

A UUID identifies each input. Same UUID and input returns the existing job; changed input is rejected. Plans are validated against a local tool allowlist and argument bounds. Notes and timers require explicit confirmation. Local effects and their receipts commit in one SQLite transaction. Repeated confirmation returns the completed result. Plans remain available after failures. Research jobs count toward the queue limit.

The planner receives up to four completed request/reply/receipt turns. Dismissed or interrupted jobs are excluded. Pending HTTP work can be cancelled independently of camera capture; stale session/turn requests and late terminal-state updates are rejected. Already completed effects are not undone. Job polling continues without a camera socket because agent work can outlive capture.

SQLite operations are short synchronous transactions within a single-user service. Their lock timeout can still block an async caller under contention. A multi-user deployment needs asynchronous database boundaries and isolation; current software tests do not establish that capacity.

## HTTP surface

All API HTTP routes require the app bearer token. Camera authentication occurs in the first WebSocket message after origin validation. Static assets expose no runtime directory.

| Route | Purpose |
| --- | --- |
| `GET /api/status` | Readiness and capabilities |
| `WS /api/stream` | Camera packets, caption/activity events and controls |
| `GET/POST/DELETE /api/provider/config` | Provider connection without returning its key |
| `POST /api/provider/assist` | Select an existing candidate |
| `POST /api/provider/voice` | Optional generated caption speech |
| `GET/POST /api/agent/jobs` | Read or submit jobs |
| `POST /api/agent/jobs/{id}/{confirm,cancel,dismiss}` | Existing review and correction operations |
| `POST /api/agent/interrupt` | Interrupt pending jobs |
| `POST /api/export` | Bounded MP4 conversion |

The `/api/openai/*` compatibility routes remain available; new integrations use the generic provider routes. The API has no stable external versioning promise. [Setup](SETUP.md) and [security](../SECURITY.md) describe deployment and data boundaries.

## Extend existing components

Add provider protocols in `provider.py`, retaining server-side keys and local plan validation. Add tools through schema, validator, executor, receipt labels and tests together. Remote writes require idempotency and reconciliation beyond local transactions. Preserve the video-only protocol, real timing and abstention semantics when investigating recognition changes. Evaluate a measured gap before adding model or framework dependencies.

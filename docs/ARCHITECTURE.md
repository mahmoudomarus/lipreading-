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
| Commands mode phrase matching and saved-name correction | `commands.py` |
| Existing abstention and repetition heuristics | `recognition_guard.py` |
| Structured text provider adapter | `provider.py` |
| Durable jobs, validated tools and receipts | `agent.py` |
| Cited report and public-link validation | `web_results.py` |
| Optional generated-caption speech adapter | `speech.py` |
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

The recognizer repeatedly processes offline windows. The advice thresholds for face size and head angle are stricter than rejection thresholds so the UI can suggest improvements before capture fails. [Recognition limitations](../README.md#1-what-it-is).

Single-part turns retain their native alternatives. Multi-part turns keep earlier best readings and substitute only alternatives from the last part, with at most two distinct full-turn alternatives. Drafts are joined only when every part supplied real draft text. A held part keeps the complete turn held. Manual comparison uses the existing text selector and is disabled when no distinct supported candidate exists. Automatic selection is not enabled on assembled visual turns. Automatically sent turns pass up to two alternatives with the request; the planner receives them as `other_readings` (stored in the job's nullable `alternatives` column, added in place on older databases) to infer garbled requests, and write tools still require confirmation.

## Agent state and execution

```text
queued -> thinking -> completed                 answer or read-only tools
                 -> researching -> completed   cited research
                 -> review -> completed         confirmed local writes
                           -> cancelled
queued -> cancelled
queued, thinking, researching, review -> cancelled
thinking, researching -> failed                 request failure or restart
finished automatic lip job -> dismissed         excluded from future context
```

A UUID identifies each input. Same UUID and input returns the existing job; changed input is rejected. Plans are validated against a local tool allowlist and argument bounds. Notes and timers require explicit confirmation. Local effects and their receipts commit in one SQLite transaction. Repeated confirmation returns the completed result. Plans remain available after failures. Research jobs count toward the queue limit.

The planner receives up to four completed request/reply/receipt turns. Dismissed and cancelled jobs are excluded. Pending HTTP work can be cancelled explicitly; late terminal-state updates are rejected. Speech never cancels tasks and each eligible final turn is independently submitted. Already completed effects are not undone. Job polling continues without a camera socket because agent work can outlive capture.

The worker maintains at most `AGENT_MAX_CONCURRENT_JOBS` tasks (default 3), and claims queued work atomically. Each job uses its own provider snapshot and up to four completed earlier tasks; it does not await sibling tasks for context. Queue capacity checks and insertion share a transaction. Pending confirmations do not consume running slots and remain in listings beyond the thirty-job history window.

Async routes and job processing offload SQLite transactions to threads. SQL operations are drained before cancellation cleanup; database locks therefore do not block camera event handling. Explicit Cancel and Stop all mark terminal cancellation before cancelling the corresponding provider await. Terminal guards prevent late plans, research or failures from restoring a cancelled task. Cancel and edit is an explicit per-job cancellation followed by a new UUID, so stale confirmations cannot execute replaced details.

## HTTP surface

All API HTTP routes require the app bearer token. Camera authentication occurs in the first WebSocket message after origin validation. Static assets expose no runtime directory.

| Route | Purpose |
| --- | --- |
| `GET /` and static files | Camera application, no bearer required |
| `GET /api/status` | Readiness and capabilities |
| `WS /api/stream` | Camera packets, caption/activity events and controls |
| `GET/POST/DELETE /api/provider/config` | Provider connection without returning its key |
| `POST /api/provider/assist` | Select an existing candidate |
| `POST /api/provider/voice` | Optional generated speech for assistant replies and captions |
| `GET/POST /api/agent/jobs` | Read or submit jobs |
| `POST /api/agent/jobs/{id}/{confirm,cancel,dismiss}` | Existing review and correction operations |
| `POST /api/agent/cancel-all` | Cancel all queued, running and review jobs |
| `GET /api/phrases`, `POST /api/phrases` | Read or replace the Commands mode phrase list (up to 60 phrases) |
| `POST /api/agent/jobs` `purpose` | `assist` (default) answers the request; `speak` only reconstructs the user's sentence (`understood`, `certainty`) for the client to say aloud, and never proposes actions |
| `GET /api/vocabulary`, `POST /api/vocabulary` | Read or replace saved names and places used to correct readings and given to the planner |


## Extend existing components

Add provider protocols in `provider.py`, retaining server-side keys and local plan validation. Add tools through schema, validator, executor, receipt labels and tests together. Remote writes require idempotency and reconciliation beyond local transactions. Preserve the video-only protocol, real timing and abstention semantics when investigating recognition changes. Evaluate a measured gap before adding model or framework dependencies.

## Shared configuration

`config.py` defines protocol 4, first draft context 1.35 s, draft interval 0.9 s, minimum capture 0.7 s, maximum decode window 8.0 s, Phrase limit 7.8 s, buffer limit 9.8 s / 260 frames, and the validated concurrency limit (default 3, range 1 to 12). These are scheduling bounds, not measured delivery latency. Quality, mouth activity and recognition each have a separate single-thread executor; all agent tasks share one async worker with bounded concurrency. Failed scheduled camera work sends an error before closing the socket.

Camera-session logs retain metadata for frame delivery, lip-activity transitions, decode time, holds and the close reason. They omit transcripts and keys. A 25-second receive timeout sends an explanatory error before closing; the browser retains the error while checking server readiness.

# Changelog

## Unreleased

A spoken reply now stops only when a new reading of the user's words arrives, not on any lip movement, so smiling or reacting no longer cuts it off. Unread turns during or just after a reply are not reported as failures.

Count only lip movement, not the closing pause, when deciding whether an unread turn was real speech. Brief reactions between sentences no longer show "I didn't catch that".

Judge face size in pixels instead of share of frame. The old 28% rule refused faces the recognizer reads correctly; a 93 px face now reads, while faces under 85 px are still refused with guidance.

Add an understanding step: the planner first reconstructs the sentence the user most likely said, with a certainty rating, shown beside the raw lip reading, and answers that sentence. Add Speak for me, which says the understood sentence aloud instead of answering it.

Report speaking turns that yield no words instead of dropping them silently, and stop a flickering face from holding a turn open.

Add saved names and places: reading spans that look like a saved name on the lips are corrected in every mode, the original reading stays visible, and the planner receives the list.

Add Commands mode: finished turns snap to the closest saved phrase using spelling and lip-shape similarity, or are held when no phrase fits clearly. Phrases are edited in Settings and stored locally.

Send up to two alternative lip readings with each automatic request so the assistant can resolve look-alike misreads, stating its guess. Notes and timers proposed from a guess still require confirmation.

Remove the recording studio, MP4 export route and FFmpeg dependency. Speak each new assistant reply aloud behind a Speak replies switch; lip movement stops playback without cancelling tasks. Smooth lip shapes and require sustained movement so turns end on small or noisy faces.

Update the camera send-rate display on a timer so stalled delivery reports zero instead of retaining a stale FPS value.

Retain camera-stall errors across connection close/readiness updates and log session/decoder metadata without captions or keys. Report receive timeouts before closing.

Print and save a private direct computer link separately from the phone tunnel link, so desktop-camera testing uses loopback.

Resume a user-started camera session when its tab becomes visible again, after the old capture finishes. Keep capture off while hidden, retain explicit Stop behavior and clear stale FPS. Show intentional pause separately from connection failure.

Remove the unused provider-specific compatibility routes, retaining caption speech behind the generic provider route. Review holds are kept by default. Surface camera-session failures before closing and normalize combined alternatives.

Run background jobs concurrently with a configurable default limit of three. Speech only stops caption audio; it no longer cancels jobs, pending confirmations or older finished turns. Add per-task cancellation, Cancel and edit, and Stop all. Keep terminal cancellation and request UUIDs authoritative, preserve pending confirmations beyond the history window, and offload async SQLite work from the event loop.

Correct action previews and reject malformed camera control values. Preserve drafts, alternatives and review holds across visual turns. Extract startup-owned runtime resources and a testable camera session. Enforce lint in CI, retain failed plans, account for research in queue bounds and report launcher timeouts as failures. See `docs/BASELINE.md` for repeated timing measurements and `docs/RECORDING.md` for the first labeled evaluation protocol.


Add local lip-shape turn detection, pause-based utterance assembly, cited web research, sandboxed page cards, and downloadable Markdown drafts. See `docs/TURN_TAKING.md` for implemented behavior and limits.

Prevent empty visual drafts from triggering fluent beam-decoder guesses; hold repetitive, unsupported and recent duplicate long readings. Add silence abstention and Misread dismissal with context isolation. Pace camera delivery to 25 FPS without reducing sensor cadence to 15 FPS. Upgrade the default conversation model to GPT-6.1 Sol with low reasoning effort; text provider remains replaceable.


Live conversation sends finalized visual predictions to the agent automatically, with optional manual review. Automatic turns retain provenance and idempotency IDs; drafts are excluded. Notes and timers still require confirmation. Poll responses preserve recent/completed turns rather than rolling the UI backward.

## 0.1.0 on 2026-11-01

Initial public research prototype: phone-camera visual captions, reviewed text requests, replaceable text providers, local note/timer/calculator tools, durable jobs and receipts, and a recording studio. Includes protocol/agent/UI/export tests, source packaging, asset verification, setup documentation, research findings, and a contribution roadmap.

Accuracy and true streaming recognition remain open problems. See `docs/MEASUREMENTS.md` for the scope of existing checks.

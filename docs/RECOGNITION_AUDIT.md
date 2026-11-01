# Current implementation audit — 1 November 2026

Scope: inspect and improve the existing demo, preserving its architecture and camera-only path. No recognizer replacement, new model, framework, rewrite layer, or confidence percentage was added. The running phone service was not restarted. The only product experiment is disabled by default.

## What exists

| Stage | Actual implementation |
| --- | --- |
| Camera → transport | `phone-app/dist/app.js` requests `audio: false`, captures JPEGs with capture timestamps, and sends binary WebSocket packets. Replay uses the same packet format and real-time pacing; audio is never decoded or sent. |
| Framing and timing | `engine.py` resamples to 25 FPS, rejects slow/discontinuous/orientation-changing clips, requires one sufficiently large frontal face, and uses cached face detections plus the upstream smoothed affine cropper to obtain 96 × 96 mouth patches. A separate `QualityMonitor` reports brightness, sharpness, distance and head turn. These are framing signals, not correctness estimates. |
| Recognition | Offline Auto-AVSR video checkpoint, repeatedly encoded on growing windows. Greedy CTC gives drafts; beam search combines attention decoder 0.9, CTC 0.1 and a trained subword language model 0.3. CPU, four threads, fast beam 4 / detailed beam 12. This trained LM is already part of the main baseline. |
| Candidates and scores | `LipReader.refine` deduplicates up to eight beam hypotheses, exposes the best plus two alternatives. Upstream hypotheses have combined `score` and per-scorer `scores`, but the adapter discards these. Neither scores nor quality values are calibrated probabilities. The total beam score mixes linguistic and visual-conditioned evidence. |
| Turns | `MouthMonitor`/`LipActivity` detects movement and a 1.05 s visual pause. `Utterances` assembles native windows; visual turns, not intermediate chunks, are submitted to the agent. Renewed motion can interrupt jobs. The encoder remains noncausal and does not maintain incremental decoding state. |
| Existing LLM selection | `TextProvider.assist` selects an index among supplied candidates; the server and UI reject invented alternatives. The UI supplies up to three previous displayed entries as context. This is selection, not free-form cleanup, and is explicitly unverified. The upstream `chaplin.py` has a rewrite prompt, but that executable is **not** this app's runtime path. |
| Important wiring detail | Automatic context selection is conditional on `!data.visual_turns`. On the current visual path it is not automatically called. Final turn assembly removes chunk alternatives and `draft_text`; the manual comparison button therefore often has just one candidate. Automatic agent submission uses the raw final reading, not the later display selection. Do not describe context selection as an accuracy layer already applied to every agent request. |
| Uncertainty and review | Empty drafts/no motion abstain. Guards hold repeated n-grams, implausible word expansion and strong draft/final disagreement; a recent-reading guard can hold near-duplicates. `confidence` is explicitly `null`. The UI already offers alternatives, Compare readings, repeat/correction, review, and dismissal of misread agent turns. No threshold has been calibrated against correctness. |
| Commands/context | The existing planner receives finalized text and up to four completed request/reply/receipt turns. Dismissed/interrupted turns are excluded. Local action validation, idempotency and durable receipts already exist. `save_note` and `start_timer` require explicit confirmation of the proposed details. Research, page/draft cards and calculations already work. No new execution or permission system is needed for this task. |

## Baseline saved locally

`.runtime/baseline-20261101/` contains the actual local source archive from before edits, a vendored-code archive, per-file fingerprints, exact installed package versions/platform, whitelisted runtime tuning settings, public provider configuration, checksummed diagnostic clips and full socket event reports. Credentials, jobs and model weights are excluded from the archives. All six installed model files matched `assets.json`. The public starting commit was `84f18f0ef8a81846e09fa1e9df72a357e3fa4444`; the actual local tree also contains older script/legacy bridge differences, so the local archive is the authoritative baseline, not an assumed clean Git checkout.

Main baseline: **unchanged full camera → final text path**, local socket, visual turns enabled, assist absent from that automatic path, explicit Finish at EOF. This measures delivery to the replay client, not physical-phone network latency or agent response time.

| Diagnostic | Unchanged baseline | Optional hold-preservation experiment |
| --- | --- | --- |
| Previously used public clip, last frame 2.96 s | First draft 2.197 s; final 4.778 s; last frame → final 1.818 s | First draft 2.279 s; final 4.862 s; last frame → final 1.902 s |
| Same frames + 55 frozen tail frames | First draft 1.859 s; final 5.951 s | First draft 2.093 s; final 7.142 s |
| Frozen first image | No caption, no automatic request | No caption, no automatic request |
| Raw transcript, both positive diagnostics | `THE SUNRISE WOULD BE TOO SOON` | Identical |
| Labeled held-out speakers / genuine silent mouthing | 0 / 0 | 0 / 0 |
| WER, meaning-changing errors, intent error rate, accepted-reading accuracy | **Not measurable from available footage** | **Not measurable** |

These are ordered single runs with different process warmup/load, not a latency speedup or slowdown attribution. The two positive diagnostics share the same source clip and speaker. The clip has no verified reference or acquisition provenance in the workspace and was already used repeatedly during development; it is not held out. Frozen frames are synthetic negative/endpointing controls, not natural no-speech footage or genuinely silent articulation. Earlier claims that the sample was misread lack a stored verified reference; no transcript was invented to compute WER.

## Observed errors versus hypotheses

1. **Observed user report:** an unwanted repeated preface (“I'm going to tell you a little bit…”), appearing after questions. No matching raw recording/intended transcript pair is retained. Existing repetition/expansion/recent-reading guards address this class heuristically. We cannot measure its frequency, WER or false-rejection rate from the screenshot. Treat decoder/LM expansion and segmentation as hypotheses, not proven causes.
2. **Observed saved outputs:** different drafts and alternatives converge on the same sunrise sentence across old and current diagnostics; alternatives differ in modal words or add a trailing phrase. Framing checks pass in the recorded diagnostic. That rules out a triggered framing rejection, not crop error, visual ambiguity or wrong words. There is no reference from which to rank actual substitutions.
3. **Reproduced implementation defect:** a chunk held for draft disagreement stays held in `Utterances.finish`, but `finish_turn` overwrites it with `RecognitionGuard.assess` on an assembled result that no longer contains draft evidence. The final guard can release that hold. A deterministic fixture reproduces this through the actual two components.
4. **Homophenes:** no observed reference/prediction pairs support a useful homophene map yet. In particular, do not label `would/will` or any name/number pair as a proven visual confusion based only on alternative text. Collect errors first, then have a reviewer distinguish articulatory ambiguity from tracking, capture, crop and endpoint failures. Prioritize annotated negations, numeric details and names when those recordings are available.

## Minimal experiment and rollback

`LIPREAD_PRESERVE_HOLDS=1` makes the existing guard retain an explicit incoming `auto_send=False` and its reason. It adds no layer, model call or probability. Default/unset is **0**, preserving baseline behavior. The isolated experiment used the exact saved source plus only `recognition_guard.py` and the one constructor call in `server.py`, sharing the same checksummed weights. Its temporary process was stopped afterward.

Before/after: the deterministic held-chunk fixture changes from auto-send **true → false**; an accepted-reading fixture stays accepted. Actual diagnostic clips did not exercise a held chunk, and all transcriptions stayed unchanged. This demonstrates hold preservation, **not better recognition or calibrated uncertainty**. If the upstream hold was a false positive, this change preserves that false positive and increases clarification for a correct reading. That tradeoff requires validation/held-out footage before promotion. No actual correct-to-wrong transcription example can be reported without references; the evaluator explicitly records such regressions when available, and synthetic tests verify that reporting.

Rollback: leave/unset `LIPREAD_PRESERVE_HOLDS` or set it to `0` for the next service start. The working service remains at its original default. The optional code can also be removed by reverting its two-file patch; the evaluator is independent. The saved `source.tar.gz` contains the original versions if an exact local restore is needed. No model, UI, agent tool or database migration accompanies this experiment.

## Prioritized actual gaps

| Priority | Gap and next checkpoint |
| --- | --- |
| 1 | Missing consented references, separate validation/held-out speakers **and sentences**, and genuinely silent mouthing. Obtain local paths/transcripts before claiming accuracy, tuning thresholds or changing recognition defaults. |
| 2 | Preserve existing holds across turn assembly. Optional patch reproduced; held-out accepted accuracy versus clarification and critical errors must decide promotion. |
| 3 | The old evaluator scored chunks, ignored assembled turns/holds, conflated no output with abstention, and always forced Finish. The evaluation-only patch now measures the actual final text/dispatch eligibility, records natural completion separately, retains raw events, rejects changed clips/context, and surfaces regressions. |
| 4 | Drafts/alternatives/scores are lost across interfaces. First measure candidate oracle WER and current selector accuracy/latency on labeled clips. Reuse the existing selector if useful; do not add a second reranker or unconstrained rewriting. Propagating multi-window alternatives needs its own small experiment. |
| 5 | Current guards and activity thresholds are uncalibrated; repeat guards can suppress legitimate repetition. Calibrate on validation only, then report accepted exact-reading accuracy versus hold/no-output frequency on held-out footage, with false interruptions and missed pauses. Keep confidence null. |
| 6 | Repeated noncausal encoding/refinement contributes delay. The current measurements do not justify a model/framework replacement. Only profile and test one local change at a time against the unchanged full demo. |

No recognition improvement is demonstrated or enabled by this task. [Evaluation commands and metric definitions](EVALUATION.md).

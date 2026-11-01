# How to make the idea better

The concept is a silent interface to useful software. The bottleneck is trustworthy visual input, not prettier model prose. Contributions should state a hypothesis, implement a bounded change, and show how it was evaluated. There are no promised dates or claims of perfect recognition.

| Priority | Experiment | Evidence needed before calling it an improvement |
| --- | --- | --- |
| 1 | Establish a consented validation/held-out phone corpus | Separate speakers and sentences; references withheld from inference; genuinely silent mouthing, natural no-speech and hard negatives included |
| 2 | Evaluate the optional existing-hold preservation fix | Compare accepted-reading accuracy, clarification, critical/intent errors and latency against the frozen full-demo baseline; default remains off |
| 3 | Investigate observed crop, capture and timing errors | Change one existing component at a time only where labeled failures justify it; same-clip WER and latency, including regressions |
| 4 | Evaluate existing candidates/context selection and guards | Candidate oracle WER, selection mistakes and added latency; validation-only threshold calibration and held-out acceptance/clarification tradeoff; no duplicate LLM layer |
| 5 | Reduce waste in inference and transport | Stage-level timing, memory/capture continuity, numerical or transcript equivalence where claimed, controlled warmup/load |
| 6 | Improve agent portability and execution | Protocol fixtures, malformed responses, timeouts, retries, interrupted jobs, duplicate requests/confirmation and provider swaps |
| 7 | Expand device usability | Documented iPhone/Android/browser recordings, rotation, camera permissions, wake lock, accessibility and exported audio/video |

## Good first contributions

- Add a tested troubleshooting entry for a real setup failure without publishing logs containing private data.
- Validate a Linux dependency/install combination and document precisely what ran: unit tests, model initialization, or full phone inference.
- Add keyboard/focus/screen-reader improvements with a reproducible before/after interaction.
- Add provider protocol fixtures that exercise refusals, incomplete JSON, throttling, and redirects without live keys.
- Improve the evaluator's per-group reports or confidence intervals while keeping references outside the recognition path.

## Larger research contributions

These are future research directions, not the current build spec. Preserve the working architecture; a new model/framework needs a measured gap and a separate controlled comparison. [Current priorities and optional patch](RECOGNITION_AUDIT.md).

A streaming model is not obtained by merely slicing an offline model into smaller calls. Provide its code/checkpoint provenance, licensing terms, causal/chunk state behavior, context/latency definition and a comparison on identical held-out clips. Do not quote audio-visual benchmark numbers as silent-video results.

Personalization should be user-controlled. Record only explicit opt-in samples, support local deletion, and keep calibration/evaluation examples separate. A small command classifier may be more useful than freeform transcription, but it must reject unfamiliar movements and phrases. Similarity is not confidence until calibrated and tested.

## Evaluation report checklist

Include hardware, OS, Python/library/model revisions, decoder settings, phone/browser, clip counts and duration, dataset consent/provenance, split rules, warmup procedure, WER/exact-match, abstentions, silence false activations, and latency distributions. Measure recognition and agent response separately. Account for correction and confirmation when reporting end-to-end task completion.

Use [the research methodology](RESEARCH.md), the [example manifest](examples/heldout.example.jsonl), and `scripts/evaluate.py`. Keep user footage out of issues and commits unless the people recorded explicitly agreed to that publication. A public sample may support a reproducible diagnostic; one sentence is not overall accuracy.

## Outside the current prototype

The current lip-activity turn detector needs held-out calibration for false interruptions and missed pauses. Arbitrary app operation, external write tools, native/wearable capture, multi-user hosting, background phone alarms and durable provider secret storage need their own designs. The browser cannot promise camera capture while a phone is locked. Preserve honest capture/prediction/action states in any demo.

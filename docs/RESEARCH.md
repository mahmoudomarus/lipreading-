# Recognition investigation — 1 November 2026

## What is actually running

The camera transport is live. The recognition model is **offline Auto-AVSR**, repeatedly run on growing windows. The noncausal encoder and autoregressive decoder reprocess context. It has no incremental decoder state. A 30 FPS camera does not imply 30 FPS text generation. First draft includes the 1.35-second context wait, preprocessing, encoding, scheduling, and network delivery. Finalization adds beam decoding. A language model has no evidence that the original camera words were correct.

A previous local socket smoke run on one public three-second clip produced its first draft at 2.736 seconds and first refined output at 6.532 seconds from capture start. The output was not a valid demonstration of accurate general lip reading. These are diagnostic timings, not a benchmark or an accuracy result. `scripts/evaluate.py` measures real socket timing without sending the reference transcript to recognition. `scripts/profile_cache.py` checks repeated detection caching against uncached output on identical windows.

## Primary sources and implications

- [Auto-AVSR](https://github.com/mpc001/auto_avsr) and [Chaplin](https://github.com/amanvirparhar/chaplin): the existing sentence recognizer and inference implementation. Published checkpoint benchmark WER does not transfer to a new camera, person, crop pipeline, or decoder configuration.
- [TorchAudio real-time ASR/VSR/AV-ASR recipe](https://github.com/pytorch/audio/blob/main/examples/avsr/README.md): provides `video` modality and `online` training/evaluation modes. Its displayed 3.9% WER result is **audio-visual**, not silent visual speech. That README is a training recipe, not a validated drop-in streaming visual checkpoint for this app. A replacement must be trained or obtained, licensed, and evaluated before enabling it.
- [LipLearner, CHI 2023](https://arxiv.org/abs/2302.05907), [authors' code](https://github.com/rkmtlab/LipLearner): customizable mobile silent commands using few-shot learning. This supports investigating a separate personalized command recognizer with a bounded vocabulary. It does not establish unlimited sentence transcription accuracy, and no LipLearner accuracy is claimed for our implementation.
- [VALLR](https://arxiv.org/abs/2503.21408): visual-to-phoneme and language-model methods address ambiguity; visually similar speech remains an information constraint. A more fluent decoder is not proof of better visual evidence.
- [Apple camera controls](https://www.apple.com/privacy/control/): background camera access is disabled on iOS/iPadOS. Do not promise locked-phone/PWA background capture. Jobs on the computer can continue after the browser closes.
- [Ollama compatible API](https://docs.ollama.com/api/openai-compatibility) and [Gemini compatible API](https://ai.google.dev/gemini-api/docs/openai): compatible chat endpoints allow replaceable text providers. Compatibility is not identical model behavior. All tool proposals undergo local validation.

## Implemented now

- Separate recognition, text provider, job store, and local tool executor.
- Review editable final predictions before sending requests. Drafts never automatically invoke tools.
- Validate tool names and arguments, then require confirmation for notes/timers. Persist execution and receipt together. A duplicate request ID with changed words is rejected.
- Show actual job states and receipts; no fake confidence or simulated live output.
- Cache detections for identical captured frames within a session. Reset the cache between camera sessions. Do not cache unstable crop boundaries or noncausal encoder state.
- Report last-frame-to-draft latency on the phone, separately from server processing time. This includes the phone connection and local processing; it is not time from utterance start.

## What must happen before calling it reliable

Collect consented, labeled clips from the intended user/phone, including ordinary speech, silence, unrelated movement, head turns, poor light, and ambiguous requests. Keep calibration and held-out evaluation sessions separate; vary dates, distance, and lighting. Never supply reference text to inference or include typed corrections in accuracy scores.

Use a JSONL manifest such as:

```json
{"video":"heldout/clip-01.mp4","reference":"start a five minute timer","group":"day2-front-camera"}
{"video":"heldout/silence-01.mp4","reference":"","expected_silence":true,"group":"day2-front-camera"}
```

Run:

```sh
.venv/bin/python scripts/evaluate.py path/to/manifest.jsonl --mode live --report .runtime/heldout-live.json
```

Track corpus WER, exact request match, silence false activations, abstentions, first draft latency, last-frame-to-draft p50/p95, final latency after capture, and confirmed action correctness. Word error rate can exceed 100% when insertions are large. No measured personal accuracy exists until those clips are collected.

The next model experiment should compare an actually streaming, visual-only checkpoint against this baseline on the same held-out clips. A separate personalized command classifier needs negative examples, held-out threshold calibration, and an abstain outcome; never force the nearest command or report embedding similarity as confidence. No personalized classifier is implemented yet.

## Deliberate limits

The agent can answer from model knowledge, calculate, save local notes, and start local timers. It cannot browse, operate arbitrary apps, send email, post, purchase, or run shell commands. Timers use persisted due times and update on reconnect; there is no push notification or background alarm delivery while the phone is closed. Computer sleep suspends work. Provider requests have bounded timeouts and fail visibly. Jobs interrupted by server restart are marked failed instead of silently repeated.

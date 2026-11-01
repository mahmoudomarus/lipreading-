# Recording a first evaluation set

## Participants and separation

Use three consenting adults if possible. The supplied templates define 20 validation clips from speaker A and 30 held-out clips from speakers B and C, for 50 total. Two people can record the A and B sets for 40 clips. If only one person is available, use separate sessions and label the result a personal diagnostic; do not describe it as performance on unseen speakers.

The templates are recording prompts and intended labels, not collected or verified data. Speaker and sentence sets are disjoint between validation and held-out sets. Each speech prompt has one voiced and one genuinely silent-mouthing recording within its assigned split. Natural rest and unrelated movement are negative controls.

## Capture procedure

1. Agree on local evaluation and any publication separately. Use anonymous participant IDs, record device/browser, session, light and distance, and keep personal footage out of Git.
2. Use the phone camera facing the speaker, with clear light and a stable frontal face. Record the actual face rather than a screen replay. Keep reference text, predictions and subtitles out of the image.
3. Record each prompt as its own video. Leave about one second of rest before articulation and three seconds after. Speak naturally for the voiced version. For silent mouthing, articulate without voicing or whispering; muting voiced footage is not equivalent.
4. For controls, follow the recording instruction without an intended phrase. Avoid interpreting a smile or jaw motion as an empty spoken sentence.
5. A human should verify the intended transcript and capture condition, record any mistakes, and label the last articulation time as `speech_end_seconds` if end-of-speech latency is needed. Audio tracks, if present in files, are ignored by the evaluator.
6. Copy the templates into a private `evaluation-data/` directory, update video paths to existing files, and review expected tool details. Partial expected-action fields deliberately test only those slots; add exact note text or URLs only when those were the intended details.

## Prompts and manifests

- [Validation template](examples/recording-validation.template.jsonl), speaker A, eight phrases in both conditions plus four controls.
- [Held-out template](examples/recording-heldout.template.jsonl), speakers B and C, twelve phrases in both conditions plus six controls.

Do not inspect held-out outputs while tuning. Keep inference context empty for this first set. Run validation for threshold selection, freeze the candidate change, and evaluate the held-out set once for the comparison. Record all regressions, not just examples that improved.

```sh
.venv/bin/python scripts/evaluate.py evaluation-data/validation.jsonl \
  --report .runtime/validation.json
.venv/bin/python scripts/evaluate.py evaluation-data/heldout.jsonl \
  --validation-manifest evaluation-data/validation.jsonl \
  --report .runtime/heldout.json
```

Use `--endpoint natural` on clips containing their recorded final pause. Use `--plan-intents` only with a matching configured provider; it is a dry run and executes no tools. Report voiced and silent-mouthing WER separately, accepted exact-reading accuracy, clarification/no-output frequency, critical and reviewed semantic errors, no-speech false activations, and latency p50/p95. [Metric definitions](EVALUATION.md).

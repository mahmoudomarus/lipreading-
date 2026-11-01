# Changelog

## Unreleased

Live conversation sends finalized visual predictions to the agent automatically, with optional manual review. Automatic turns retain provenance and idempotency IDs; drafts are excluded. Notes and timers still require confirmation. Poll responses preserve recent/completed turns rather than rolling the UI backward.

## 0.1.0 — 2026-11-01

Initial public research prototype: phone-camera visual captions, reviewed text requests, replaceable text providers, local note/timer/calculator tools, durable jobs and receipts, and a recording studio. Includes protocol/agent/UI/export tests, source packaging, asset verification, setup documentation, research findings, and a contribution roadmap.

Accuracy and true streaming recognition remain open problems. See `docs/MEASUREMENTS.md` for the scope of existing checks.

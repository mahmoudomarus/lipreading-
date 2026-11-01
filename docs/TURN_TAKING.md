# Visual turns, interruption, and work cards

The live mode now separates mouth activity from word recognition. A local MediaPipe Face Landmarker measures normalized lip-shape changes at roughly 8 samples/second. Two movement observations in a short window start a turn; approximately 1.05 seconds without further detected movement ends it. Camera audio is never requested. Missing face tracking is not treated as proof that the user finished speaking.

The word decoder still processes offline windows. A live socket diagnostic detected a pause at capture time 4.16 seconds and emitted the assembled utterance at 6.15 seconds without a manual finish; decoding therefore still adds noticeable delay. The diagnostic transcript remained inaccurate, so this is endpointing evidence, not word-accuracy evidence. For longer turns, consumed windows are assembled and sent to the agent only after the visual pause. Intermediate windows remain captions, not separate agent requests. A manual **Finish sentence** control remains available. This does not turn the recognition model into a causal streaming model or establish transcription accuracy.

When Live replies is on, renewed sustained lip movement interrupts queued, thinking, researching, or unconfirmed jobs. The asynchronous HTTP request is cancelled locally and the worker can accept a new job. Interrupted jobs remain in the audit record and are excluded from future model context. A late response cannot restore them. Camera session/turn identifiers also reject delayed requests from an older spoken turn. Already completed actions are not undone; a provider may continue processing/billing a request after local cancellation.

The UI shows **Listening**, **You paused / finishing**, **Thinking**, **Researching**, and **Your turn**. **Stop answer** and **Interrupt** provide manual fallback. Playing generated caption audio is stopped, and late audio from an interrupted generation is discarded. Generated agent speech is not automatic in this version.

## Work in the conversation

| Tool | Actual behavior |
| --- | --- |
| `research` | One bounded web-search request through the included Responses adapter, up to three built-in tool calls. Returns a report with provider-originated citation spans. No completed search or no valid citations means an error rather than an unsourced substitute. |
| `open_page` | Creates a page-preview card with a sandboxed iframe and explicit external-page link. Some sites prohibit embedding. It does not operate arbitrary desktop apps or silently open browser tabs. |
| `draft_document` | Creates an inert Markdown work product in the job receipt, with an in-chat preview and client-side download. No arbitrary filesystem write or code execution occurs. |

Research is currently available for the included hosted Responses connection. Other text endpoints retain their existing tools and need a compatible research adapter for live research. The capability is reported by `/api/provider/config`; unsupported connections must not claim they searched. A research action is a standalone plan; notes and timers retain their confirmation step.

Example requests: “Research how NASA explains the phases of the Moon,” “Draft a plan for a weekend coding project,” and “Open https://example.com.” Typed requests are useful for validating tools independently of recognition errors.

## Verification and limits

A public speech clip produced a lip-activity start at 0.24 seconds and a stop at 4.08 seconds after a roughly three-second clip plus frozen tail. A static-face clip produced no start events. These are diagnostics, not validated speaker-independent endpointing accuracy. Smiles, chewing, head movement, poor tracking, and atypical articulation can still cause false starts, interruptions, or missed pauses. A held-out, consented phone corpus is still required.

Unit tests cover movement/pause hysteresis, lost tracking, ordered utterance assembly, interruption freeing a blocked worker, stale completion protection, source validation, cited research parsing, work receipts, and client turn identifiers. Real API tests produced a cited research result, a generated document receipt, and a page card. Browser camera/iframe/download/audio behavior needs checks on target devices.

# Visual turns and work cards

## Camera conversation

A local face-landmarker checks normalized lip-shape changes at roughly eight samples per second. Two movement observations in a short window start a turn; approximately 1.05 seconds without sufficient movement ends it. Tracking loss does not count as a completed phrase. Finish sentence provides a manual fallback.

Consumed decoder windows form a single final request. Intermediate chunks remain captions and do not become separate agent jobs. Final turns retain actual draft evidence and bounded alternatives; an uncertain part holds the whole turn for review. Compare readings is available only when at least two distinct supported readings exist. It selects among candidates without rewriting them.

With Live replies enabled, every eligible finalized turn becomes its own task. A newer turn does not suppress an older finished reading. Lip movement only stops generated caption audio; it never changes job state or clears unsent requests. Live replies can be disabled for manual review.

Agent work runs concurrently up to `AGENT_MAX_CONCURRENT_JOBS` (default 3). Pending confirmations remain available. Cancel stops a selected queued, thinking, researching or review job. Stop all cancels all those jobs and unsent client requests. Cancel and edit replaces the selected task with a new request UUID after cancelling the old one. Completed effects are not undone. A provider can continue processing/billing after local cancellation.

The UI shows listening and finishing separately from the background task count. Generated agent speech is not automatic. Job polling continues without a camera socket because background work can outlive capture.

## Work in chat

Research returns a source-linked report. Open page returns a sandboxed preview and an external link, since some sites block embedding. Draft document returns Markdown with preview, copy and download controls. These cards display actual tool receipts. Notes and timers retain their confirmation step.

Research uses the included Responses web-search adapter. Other text connections need an equivalent research adapter and expose capability availability through `/api/provider/config`. Example requests include "Research NASA's explanation of the Moon's phases", "Draft a weekend project plan" and "Open https://example.com". Typed requests test tools separately from recognition.

[Project limitations](../README.md#limitations) and [measurement methods](BASELINE.md) define the current evidence boundaries. Device checks should cover missed pauses, false interruptions, reconnect, page embedding, downloads and Studio audio behavior.

# Development measurements — 1 November 2026

These results are diagnostic checks on the development Mac, not representative accuracy claims. No personal held-out footage has been evaluated.

| Check | Observation |
| --- | --- |
| Earlier local WebSocket sample run | First draft 2.736 s; refined result 6.532 s from capture start |
| Updated local WebSocket sample run | First draft 2.125 s; refined result 4.852 s from capture start |
| Updated final draft | Received 3.945 s; last included captured frame 2.960 s; approximately 0.985 s frame-to-draft |
| Updated refinement | 0.91 s beam decoding; final received approximately 1.89 s after last included frame |
| Same-window detection-cache comparison | Identical greedy transcripts with/without cache across 1.4, 2.08 and 2.88 s windows |
| Cache preprocessing on 2.88 s window | 0.104 s uncached vs 0.034 s cached in this ordered diagnostic run |
| Actual text provider + isolated calculator job | 2.370 s; executed result 12 × 7 = 84 |
| Actual text provider + isolated note job | 2.131 s including test confirmation; persisted receipt verified |
| Actual text provider + isolated timer job | 1.548 s including test confirmation; due time persisted and reloaded |
| Public HTTPS tunnel + real HTTP agent job | Completed with 8 × 9 = 72 execution receipt in 2.61 s; authentication and published-site CORS passed |
| Automated tests | 40 Python and 16 JavaScript checks passed |

The sample's refined prediction remained “THE SUNRISE WOULD BE TOO SOON.” It was not accepted as accurate transcription. Detection caching preserves the output; it does not repair it. The timing improvement between runs cannot be attributed entirely to caching: warmup, scheduling and machine load are not controlled. An ordered cache microprofile is especially vulnerable to warmup bias.

Browser automation was unavailable. A version-specific generated screenshot was inspected for the published UI; camera permissions, mobile layout, browser recording, and audio mixing still require manual checks on target phones. Real model and HTTP tests are separate from browser UI verification.

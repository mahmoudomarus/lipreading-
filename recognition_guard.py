"""Conservative abstention heuristics, not a calibrated recognition confidence score."""

from collections import Counter, deque
from difflib import SequenceMatcher
import math
import re


def words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", (text or "").lower())


def review_reason(text, *, draft=None, duration=None):
    tokens = words(text)
    if not tokens:
        return "No clear visual words were detected."
    if len(tokens) >= 12:
        counts = Counter(tuple(tokens[i : i + 4]) for i in range(len(tokens) - 3))
        if counts and max(counts.values()) >= 3:
            return "This reading repeats itself. Try that phrase again."
    if duration and len(tokens) > max(8, math.ceil(float(duration) * 4.5 + 3)):
        return "Too many words were decoded for this short clip."
    if draft is not None:
        visual = words(draft)
        if not visual:
            return "The decoder had no visual draft to support this reading."
        if len(tokens) >= 6 and len(tokens) > len(visual) * 2 + 3:
            return "The decoder added too many words beyond the visual draft."
        if (
            len(tokens) >= 6
            and SequenceMatcher(None, " ".join(tokens), " ".join(visual), autojunk=False).ratio()
            < 0.42
        ):
            return "The final reading disagrees strongly with the visual draft."
    return None


class RecognitionGuard:
    def __init__(self):
        self.recent = deque(maxlen=12)

    def assess(self, result, timestamp):
        reason = review_reason(
            result.get("text"), draft=result.get("draft_text"), duration=result.get("duration")
        )
        normalized = " ".join(words(result.get("text")))
        if not reason and len(words(normalized)) >= 6:
            for previous, at in self.recent:
                if (
                    0 <= timestamp - at <= 45
                    and SequenceMatcher(None, previous, normalized, autojunk=False).ratio() >= 0.92
                ):
                    reason = "This is very close to a recent reading. It was not sent again."
                    break
        if not reason:
            self.recent.append((normalized, timestamp))
        return {
            "auto_send": reason is None,
            "needs_review": reason is not None,
            "review_reason": reason,
        }

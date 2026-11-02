"""Command mode: snap a noisy lip reading to one of the user's own phrases, or hold it."""

import re
from difflib import SequenceMatcher

DEFAULT_PHRASES = [
    "Yes",
    "No",
    "Thank you",
    "Please wait",
    "I need help",
    "Can you repeat that",
    "Hello how are you",
    "Tell me a joke",
    "Set a timer for five minutes",
    "Set a timer for ten minutes",
    "Show my timers",
    "Show my notes",
    "What is in the news today",
    "What is the weather today",
]
MAX_PHRASES = 60
MAX_PHRASE_LENGTH = 120

# Letters grouped by how they look on the lips: lip closure, lip-teeth contact, rounding,
# open vowels, and sounds made inside the mouth that are mostly invisible.
_SHAPES = {
    **dict.fromkeys("pbm", "P"),
    **dict.fromkeys("fv", "F"),
    **dict.fromkeys("wqou", "W"),
    **dict.fromkeys("aeiy", "A"),
    **dict.fromkeys("tdnszlckgxjhr", "T"),
}


def words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def lip_shapes(text):
    """Collapse each word to its lip-shape sequence so look-alike words compare as equal."""
    shaped = []
    for word in words(text):
        code = "".join(_SHAPES.get(ch, "") for ch in word)
        shaped.append(re.sub(r"(.)\1+", r"\1", code))
    return " ".join(shaped)


def similarity(reading, phrase):
    spelled = SequenceMatcher(None, " ".join(words(reading)), " ".join(words(phrase))).ratio()
    shaped = SequenceMatcher(None, lip_shapes(reading), lip_shapes(phrase)).ratio()
    return (spelled + shaped) / 2


def match(candidates, phrases):
    """Return (phrase, score) when one phrase clearly fits a candidate reading, else None."""
    scored = []
    for phrase in phrases:
        best = max((similarity(c, phrase) for c in candidates if words(c)), default=0.0)
        scored.append((best, phrase))
    if not scored:
        return None
    scored.sort(reverse=True)
    best, phrase = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    # Short phrases are easy to hit by chance, so they need a closer fit.
    needed = 0.85 if len(words(phrase)) <= 2 else 0.72
    if best >= needed and best - runner_up >= 0.06:
        return phrase, round(best, 3)
    return None


def apply(result, phrases):
    """Replace a finished turn with the matched phrase, or hold it when nothing fits."""
    candidates = [result.get("text", ""), *result.get("alternatives", [])]
    found = match(candidates, phrases)
    if found is None:
        return {
            **result,
            "auto_send": False,
            "needs_review": True,
            "review_reason": "That did not match one of your phrases. Try again or edit it.",
        }
    phrase, score = found
    return {
        **result,
        "text": phrase,
        "heard": result.get("text", ""),
        "command_score": score,
        "alternatives": [],
        "auto_send": True,
        "needs_review": False,
        "review_reason": None,
    }


def clean_phrases(phrases):
    if not isinstance(phrases, list) or len(phrases) > MAX_PHRASES:
        raise ValueError(f"Use a list of up to {MAX_PHRASES} phrases.")
    kept = []
    for phrase in phrases:
        if not isinstance(phrase, str) or len(phrase) > MAX_PHRASE_LENGTH:
            raise ValueError(f"Keep each phrase under {MAX_PHRASE_LENGTH} characters.")
        phrase = " ".join(phrase.split())
        if words(phrase) and phrase.lower() not in {k.lower() for k in kept}:
            kept.append(phrase)
    return kept


def correct_terms(text, terms, threshold=0.75):
    """Replace word spans that look like one of the user's names or places on the lips.

    Returns the corrected text and the list of (heard span, term) replacements.
    """
    tokens = (text or "").split()
    candidates = []
    for term in terms:
        size = len(words(term))
        letters = len("".join(words(term)))
        # One-word names collide with short common words, so they need a closer fit.
        needed = max(threshold, 0.85) if size == 1 else threshold
        for width in {max(1, size - 1), size, size + 1}:
            for start in range(0, len(tokens) - width + 1):
                span = " ".join(tokens[start : start + width])
                if not 0.6 * letters <= len("".join(words(span))) <= 1.6 * letters:
                    continue
                score = similarity(span, term)
                if score >= needed and words(span) != words(term):
                    candidates.append((score, start, width, term))
    replaced, used = [], set()
    for _score, start, width, term in sorted(candidates, reverse=True):
        positions = set(range(start, start + width))
        if positions & used:
            continue
        used |= positions
        replaced.append((start, width, term))
    if not replaced:
        return text, []
    changes = []
    for start, width, term in sorted(replaced, reverse=True):
        changes.append((" ".join(tokens[start : start + width]), term))
        tokens[start : start + width] = [term]
    return " ".join(tokens), changes[::-1]

"""Offline evaluation only. References and annotations never enter recognition."""

import hashlib
import json
import math
import re
import statistics
from collections import Counter


def tokens(text):
    return re.findall(r"\w+(?:['’]\w+)?", (text or "").lower().replace("’", "'"))


def alignment(reference, prediction):
    a, b = tokens(reference), tokens(prediction)
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        table[i][0] = i
    for j in range(len(b) + 1):
        table[0][j] = j
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            table[i][j] = min(
                table[i - 1][j] + 1,
                table[i][j - 1] + 1,
                table[i - 1][j - 1] + (x != y),
            )
    i, j, edits = len(a), len(b), []
    while i or j:
        if i and j and table[i][j] == table[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            if a[i - 1] != b[j - 1]:
                edits.append({"op": "substitute", "at": i - 1, "from": a[i - 1], "to": b[j - 1]})
            i, j = i - 1, j - 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            edits.append({"op": "delete", "at": i - 1, "from": a[i - 1], "to": ""})
            i -= 1
        else:
            edits.append({"op": "insert", "at": i, "from": "", "to": b[j - 1]})
            j -= 1
    return {"word_errors": table[-1][-1], "reference_words": len(a), "edits": edits[::-1]}


def score(reference, prediction, critical_spans=()):
    if reference is None:
        return {
            "word_errors": None,
            "reference_words": None,
            "wer": None,
            "exact": None,
            "edits": [],
            "critical_span_errors": None,
        }
    result = alignment(reference, prediction)
    result["wer"] = (
        result["word_errors"] / result["reference_words"] if result["reference_words"] else None
    )
    result["exact"] = tokens(reference) == tokens(prediction)
    checks = []
    for span in critical_spans:
        phrase = tokens(span["text"])
        if not phrase:
            raise ValueError("A critical span cannot be empty.")

        def count(text, phrase=phrase):
            seq = tokens(text)
            return sum(
                seq[i : i + len(phrase)] == phrase for i in range(len(seq) - len(phrase) + 1)
            )

        expected, actual = count(reference), count(prediction)
        if not expected:
            raise ValueError("Critical spans must occur in the reference.")
        checks.append({"kind": span["kind"], "text": span["text"], "error": expected != actual})
    result["critical_span_checks"] = checks
    result["critical_span_errors"] = sum(x["error"] for x in checks) if checks else None
    return result


def action_match(expected, actual):
    """Compare tool identity and explicitly annotated slots; never execute tools."""
    if expected is None or actual is None:
        return None
    if len(expected) != len(actual):
        return False
    return all(
        all(action.get(k) == v for k, v in label.items())
        for label, action in zip(expected, actual, strict=True)
    )


def selected_events(events, visual, endpoint):
    # The UI replaces chunks with assembled turns. Scoring both double counts words.
    usable = [e for e in events if endpoint != "natural" or not e.get("after_finish")]
    final_type = "utterance" if visual else "result"
    by_id = {}
    for event in usable:
        if event.get("type") == final_type:
            key = event.get("turn_id") if visual else event.get("sequence")
            by_id[key] = event
    return list(by_id.values())


def summarize(rows):
    labeled = [r for r in rows if r["word_errors"] is not None and not r.get("expected_silence")]
    accepted = [r for r in labeled if r["accepted"]]
    negatives = [r for r in rows if r.get("expected_silence")]
    errors = sum(r["word_errors"] for r in labeled)
    count = sum(r["reference_words"] for r in labeled)
    intents = [r for r in rows if r.get("intent_correct") is not None]
    critical = [r for r in labeled if r.get("critical_span_errors") is not None]

    def latency(key):
        values = sorted(r[key] for r in rows if r.get(key) is not None)
        return {
            "n": len(values),
            "p50": statistics.median(values) if values else None,
            "p95": values[min(len(values) - 1, max(0, math.ceil(0.95 * len(values)) - 1))]
            if values
            else None,
        }

    return {
        "clips": len(rows),
        "labeled_speech_clips": len(labeled),
        "word_errors": errors,
        "reference_words": count,
        "wer": errors / count if count else None,
        "accepted_labeled_clips": len(accepted),
        "accepted_reading_exact_accuracy": sum(r["exact"] for r in accepted) / len(accepted)
        if accepted
        else None,
        "clarification_frequency": sum(not r["accepted"] for r in labeled) / len(labeled)
        if labeled
        else None,
        "no_final_result_clips": sum(not r["finals"] for r in rows),
        "negative_clips": len(negatives),
        "negative_caption_activations": sum(bool(r["prediction"]) for r in negatives),
        "negative_auto_send_activations": sum(r["auto_send_count"] > 0 for r in negatives),
        "critical_span_errors": sum(r["critical_span_errors"] for r in critical)
        if critical
        else None,
        "critical_span_note": "Annotated name/number/negation exact-span proxy, not semantic adjudication.",
        "command_intent_evaluated": len(intents),
        "command_intent_errors": sum(not r["intent_correct"] for r in intents) if intents else None,
        "meaning_change_reviewed_clips": sum("semantic_review" in r for r in rows),
        "meaning_changing_errors": sum(
            r["semantic_review"]["meaning_change"] for r in rows if "semantic_review" in r
        )
        if any("semantic_review" in r for r in rows)
        else None,
        "latency_seconds": {
            key: latency(key)
            for key in [
                "first_draft_seconds",
                "final_from_start_seconds",
                "final_after_last_frame_seconds",
                "final_after_speech_end_seconds",
            ]
        },
        "substitutions": [
            {"from": a, "to": b, "count": n}
            for (a, b), n in Counter(
                (e["from"], e["to"]) for r in labeled for e in r["edits"] if e["op"] == "substitute"
            ).most_common(30)
        ],
    }


def identity(row):
    keys = [
        "video_sha256",
        "reference",
        "context",
        "agent_context",
        "capture_kind",
        "split",
        "speaker",
        "critical_spans",
        "expected_actions",
        "expected_silence",
        "speech_end_seconds",
    ]
    defaults = {"context": "", "agent_context": [], "critical_spans": [], "expected_silence": False}
    return hashlib.sha256(
        json.dumps({k: row.get(k, defaults.get(k)) for k in keys}, sort_keys=True).encode()
    ).hexdigest()


def compare(before, after):
    for key in ["mode", "endpoint", "settle_seconds", "jpeg_quality", "resize_long_edge"]:
        if before.get(key) != after.get(key):
            raise ValueError(f"Comparison changed capture setting: {key}")
    left = {r["id"]: r for r in before["results"]}
    right = {r["id"]: r for r in after["results"]}
    if (
        set(left) != set(right)
        or len(left) != len(before["results"])
        or len(right) != len(after["results"])
    ):
        raise ValueError("Comparisons require exactly the same unique clip IDs.")
    pairs = []
    for key, a in left.items():
        b = right[key]
        if identity(a) != identity(b):
            raise ValueError(f"Clip, reference, annotation or inference context changed: {key}")
        pairs.append(
            {
                "id": key,
                "before": a["prediction"],
                "after": b["prediction"],
                "wer_before": a["wer"],
                "wer_after": b["wer"],
                "correct_to_wrong": a["exact"] is True and b["exact"] is False,
                "wrong_to_correct": a["exact"] is False and b["exact"] is True,
                "accepted_before": a["accepted"],
                "accepted_after": b["accepted"],
            }
        )
    return {
        "before": summarize(before["results"]),
        "after": summarize(after["results"]),
        "correct_to_wrong": [r for r in pairs if r["correct_to_wrong"]],
        "wrong_to_correct": [r for r in pairs if r["wrong_to_correct"]],
        "pairs": pairs,
        "promotion": "Manual decision required: held-out speech and genuine silent mouthing, critical errors, clarification and latency must all be reviewed.",
    }

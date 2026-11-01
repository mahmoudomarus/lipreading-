"""Metric/protocol fixtures are synthetic, not recognition accuracy evidence."""

import asyncio
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def module(name):
    import sys

    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


metrics = module("eval_metrics")
evaluate = module("evaluate")


class EvaluationTests(unittest.TestCase):
    def test_wer_keeps_insertions_and_deletions_and_unknown_labels_unknown(self):
        result = metrics.score("do not call maya", "do call anna now")
        self.assertEqual(result["word_errors"], 3)
        self.assertEqual(metrics.score("one", "one two three")["wer"], 2)
        self.assertEqual(metrics.score("one two", "")["wer"], 1)
        self.assertIsNone(metrics.score(None, "guess")["wer"])

    def test_critical_errors_are_labeled_proxies_not_semantic_confidence(self):
        result = metrics.score(
            "do not call maya at five",
            "do call anna at nine",
            [
                {"kind": "negation", "text": "not"},
                {"kind": "name", "text": "maya"},
                {"kind": "number", "text": "five"},
            ],
        )
        self.assertEqual(result["critical_span_errors"], 3)
        with self.assertRaises(ValueError):
            metrics.score("call maya", "call maya", [{"kind": "name", "text": "anna"}])

    def test_ui_turns_replace_chunks_and_natural_does_not_count_forced_finish(self):
        events = [
            {"type": "result", "sequence": 1, "text": "chunk"},
            {"type": "utterance", "turn_id": 1, "text": "assembled"},
            {"type": "utterance", "turn_id": 2, "text": "forced", "after_finish": True},
        ]
        self.assertEqual(
            [r["text"] for r in metrics.selected_events(events, True, "natural")], ["assembled"]
        )
        self.assertEqual(len(metrics.selected_events(events, True, "finish")), 2)
        self.assertEqual(len(metrics.selected_events(events, False, "finish")), 1)

    def test_tool_intent_uses_tool_names_and_labeled_slots(self):
        self.assertTrue(
            metrics.action_match(
                [{"name": "start_timer", "seconds": 300}],
                [{"name": "start_timer", "seconds": 300, "text": "tea"}],
            )
        )
        self.assertFalse(
            metrics.action_match(
                [{"name": "start_timer", "seconds": 300}], [{"name": "start_timer", "seconds": 900}]
            )
        )
        self.assertFalse(metrics.action_match([], [{"name": "save_note"}]))
        self.assertIsNone(metrics.action_match([], None))

    def row(self, prediction="call maya"):
        return {
            "id": "x",
            "reference": "call maya",
            "video_sha256": "fixed",
            "context": "",
            "speaker": "heldout-person",
            "split": "heldout",
            "capture_kind": "silent_mouthing",
            "prediction": prediction,
            "accepted": True,
            "auto_send_count": 1,
            "finals": [{}],
            **metrics.score("call maya", prediction),
        }

    def test_comparison_rejects_changed_context_clip_and_speaker(self):
        before = {"results": [self.row()]}
        for key in ["context", "video_sha256", "speaker", "reference"]:
            after = copy.deepcopy(before)
            after["results"][0][key] = "different"
            with self.assertRaises(ValueError):
                metrics.compare(before, after)

    def test_correct_to_wrong_is_not_hidden_by_average_improvements(self):
        result = metrics.compare({"results": [self.row()]}, {"results": [self.row("call anna")]})
        self.assertEqual(len(result["correct_to_wrong"]), 1)
        self.assertEqual(result["before"]["accepted_reading_exact_accuracy"], 1)
        self.assertEqual(result["after"]["accepted_reading_exact_accuracy"], 0)

    def test_output_dependent_span_checks_do_not_change_comparison_identity(self):
        before, after = self.row(), self.row("call anna")
        spans = [{"kind": "name", "text": "maya"}]
        for row in [before, after]:
            row["critical_spans"] = spans
            row.update(metrics.score(row["reference"], row["prediction"], spans))
        self.assertEqual(
            len(metrics.compare({"results": [before]}, {"results": [after]})["correct_to_wrong"]), 1
        )

    def test_no_speech_and_held_readings_are_distinct(self):
        row = self.row("call anna")
        row.update(accepted=False, auto_send_count=0)
        summary = metrics.summarize([row])
        self.assertEqual(summary["clarification_frequency"], 1)
        self.assertEqual(summary["no_final_result_clips"], 0)
        self.assertIsNone(summary["accepted_reading_exact_accuracy"])
        self.assertIsNone(summary["command_intent_errors"])
        self.assertIsNone(summary["meaning_changing_errors"])

    def test_known_speaker_and_identical_clip_cannot_leak_across_splits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "a.mp4").write_bytes(b"first")
            (path / "b.mp4").write_bytes(b"second")
            base = {
                "id": "a",
                "video": "a.mp4",
                "reference": "hi",
                "speaker": "same",
                "split": "validation",
                "capture_kind": "silent_mouthing",
            }
            second = {
                **base,
                "id": "b",
                "video": "b.mp4",
                "split": "heldout",
                "reference": "different",
            }
            with self.assertRaises(ValueError):
                evaluate.validate_records([base, second], path / "manifest.jsonl")
            second.update(video="b.mp4", reference="hi")
            with self.assertRaises(ValueError):
                evaluate.validate_records([base, second], path / "manifest.jsonl")
            second.update(speaker="new", video="a.mp4")
            with self.assertRaises(ValueError):
                evaluate.validate_records([base, second], path / "manifest.jsonl")

    def test_selector_does_not_make_single_candidate_or_held_readings_into_evidence(self):
        class Client:
            async def post(self, *args, **kwargs):
                raise AssertionError("No selector call should occur")

        result = asyncio.run(
            evaluate.assist(
                {
                    "finals": [
                        {"text": "one"},
                        {"text": "two", "alternatives": ["too"], "auto_send": False},
                    ]
                },
                "",
                Client(),
            )
        )
        self.assertEqual(result["prediction"], "one two")
        self.assertEqual(result["added_seconds"], 0)

    def test_intent_dry_run_reuses_validator_and_does_not_create_agent_store(self):
        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                return json.dumps(
                    {
                        "answer": "Proposed",
                        "actions": [
                            {"name": "start_timer", "seconds": 300, "text": "tea", "expression": ""}
                        ],
                    }
                )

        with patch("agent.AgentStore", side_effect=AssertionError("No execution database")):
            actions = asyncio.run(evaluate.plan_intent("five minute timer", [], Provider(), False))
        self.assertEqual(actions[0]["seconds"], 300)


if __name__ == "__main__":
    unittest.main()

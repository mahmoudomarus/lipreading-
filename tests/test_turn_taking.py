import unittest

from turn_taking import LipActivity, Utterances


class TurnTests(unittest.TestCase):
    def test_empty_middle_part_does_not_add_spaces_to_alternatives(self):
        turns = Utterances()
        turns.add(1, 1, {"text": "call"})
        turns.add(1, 2, {"text": " "})
        turns.add(1, 3, {"text": "maya", "alternatives": ["anna", "anna", "maya"]})
        result = turns.finish(1, 4)
        self.assertEqual(result["text"], "call maya")
        self.assertEqual(result["alternatives"], ["call anna"])

    def test_single_part_preserves_distinct_alternatives_and_visual_draft(self):
        turns = Utterances()
        turns.add(
            1,
            1,
            {
                "text": "call maya",
                "draft_text": "CAL MIA",
                "alternatives": ["call anna", "call maya", "call anna", "call me"],
                "auto_send": True,
            },
        )
        result = turns.finish(1, 3)
        self.assertEqual(result["text"], "call maya")
        self.assertEqual(result["draft_text"], "CAL MIA")
        self.assertEqual(result["alternatives"], ["call anna", "call me"])

    def test_multi_part_alternatives_change_only_the_last_part(self):
        turns = Utterances()
        turns.add(
            1,
            2,
            {
                "text": "five minutes",
                "draft_text": "FIV MINUTS",
                "alternatives": ["nine minutes", "five seconds"],
                "auto_send": True,
            },
        )
        turns.add(
            1,
            1,
            {
                "text": "start a timer for",
                "draft_text": "START TIMER FOR",
                "alternatives": ["stop the timer for"],
                "auto_send": True,
            },
        )
        result = turns.finish(1, 8)
        self.assertEqual(result["text"], "start a timer for five minutes")
        self.assertEqual(result["draft_text"], "START TIMER FOR FIV MINUTS")
        self.assertEqual(
            result["alternatives"],
            ["start a timer for nine minutes", "start a timer for five seconds"],
        )
        self.assertIsNone(turns.finish(1, 9))

    def test_absent_draft_is_not_replaced_with_invented_evidence(self):
        turns = Utterances()
        turns.add(1, 1, {"text": "hello there"})
        self.assertNotIn("draft_text", turns.finish(1, 2))

    def test_sustained_movement_starts_and_a_visual_pause_ends_a_turn(self):
        state = LipActivity()
        self.assertIsNone(state.observe([0, 1], 0)["event"])
        self.assertIsNone(state.observe([0.04, 1], 0.12)["event"])
        self.assertEqual(state.observe([0.08, 1], 0.24)["event"], "started")
        # The server samples lips about every 0.12 s; a still mouth ends the turn.
        events = {}
        for step in range(3, 20):
            result = state.observe([0.08, 1], step * 0.12)
            if result["event"]:
                events[result["event"]] = (step * 0.12, result["turn_id"])
        self.assertIn("stopped", events)
        self.assertLess(events["stopped"][0], 0.24 + 1.05 + 0.5)
        self.assertEqual(events["stopped"][1], 1)

    def test_single_sample_landmark_jitter_does_not_keep_a_turn_open(self):
        state = LipActivity()
        for step, value in enumerate([0, 0.04, 0.08, 0.12]):
            state.observe([value, 1], step * 0.12)
        self.assertTrue(state.speaking)
        # A still face with a one-sample landmark spike every third sample.
        stopped = None
        for step in range(4, 40):
            spike = 0.02 if step % 3 == 0 else 0
            if state.observe([0.12 + spike, 1], step * 0.12)["event"] == "stopped":
                stopped = step * 0.12
                break
        self.assertIsNotNone(stopped)
        self.assertLess(stopped, 0.36 + 1.05 + 0.5)

    def test_static_face_and_tracking_loss_do_not_create_fake_turn_boundaries(self):
        state = LipActivity()
        for i in range(30):
            self.assertIsNone(state.observe([0, 1], i / 8)["event"])
        state.observe([0.04, 1], 4)
        state.observe([0.08, 1], 4.12)
        self.assertTrue(state.speaking)
        self.assertIsNone(state.observe(None, 6)["event"])
        self.assertIsNone(state.observe([0.08, 1], 7)["event"])
        self.assertTrue(state.speaking)

    def test_a_face_that_keeps_dropping_out_cannot_hold_a_turn_open(self):
        state = LipActivity()
        for step, value in enumerate([0, 0.04, 0.08, 0.12]):
            state.observe([value, 1], step * 0.12)
        self.assertTrue(state.speaking)
        stopped = None
        for step in range(4, 120):
            # Tracking is lost on every other sample while the mouth is still.
            shape = None if step % 2 else [0.12, 1]
            if state.observe(shape, step * 0.12)["event"] == "stopped":
                stopped = step * 0.12
                break
        self.assertIsNotNone(stopped)
        self.assertLess(stopped, 3)

    def test_chunks_are_assembled_once_at_the_end_in_order(self):
        turns = Utterances()
        turns.start(1, 0.2)
        turns.add(1, 2, {"text": "second part", "auto_send": True})
        turns.add(1, 1, {"text": "first part", "auto_send": True})
        self.assertEqual(turns.finish(1, 10)["text"], "first part second part")
        self.assertIsNone(turns.finish(1, 11))
        turns.start(2, 12)
        self.assertIsNone(turns.finish(2, 13))

    def test_one_unsupported_chunk_holds_the_whole_utterance(self):
        turns = Utterances()
        turns.start(1, 0)
        turns.add(1, 1, {"text": "clear part", "auto_send": True})
        turns.add(
            1, 2, {"text": "unclear part", "auto_send": False, "review_reason": "Unclear words"}
        )
        self.assertFalse(turns.finish(1, 8)["auto_send"])

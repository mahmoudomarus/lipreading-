import unittest
from turn_taking import LipActivity, Utterances


class TurnTests(unittest.TestCase):
    def test_sustained_movement_starts_and_a_visual_pause_ends_a_turn(self):
        state = LipActivity()
        self.assertIsNone(state.observe([0, 1], 0)["event"])
        self.assertIsNone(state.observe([0.04, 1], 0.12)["event"])
        self.assertEqual(state.observe([0.08, 1], 0.24)["event"], "started")
        self.assertTrue(state.observe([0.08, 1], 0.8)["speaking"])
        end = state.observe([0.08, 1], 1.4)
        self.assertEqual(end["event"], "stopped")
        self.assertEqual(end["turn_id"], 1)

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

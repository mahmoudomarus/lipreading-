import unittest

from recognition_guard import RecognitionGuard
from turn_taking import Utterances


class HoldRegressionTests(unittest.TestCase):
    def assembled(self):
        turns = Utterances()
        turns.start(1, 0)
        turns.add(
            1,
            1,
            {
                "text": "please call maya in five minutes",
                "draft_text": "no",
                "auto_send": False,
                "review_reason": "The final reading disagrees strongly with the visual draft.",
            },
        )
        return turns.finish(1, 4)

    def test_propagated_draft_preserves_disagreement_hold(self):
        result = self.assembled()
        self.assertFalse(result["auto_send"])
        self.assertEqual(result["draft_text"], "no")
        changed = RecognitionGuard().assess(result, 4)
        self.assertFalse(changed["auto_send"])
        self.assertEqual(changed["review_reason"], result["review_reason"])

    def test_default_guard_accepts_supported_text(self):
        result = {"text": "please call maya in five minutes", "auto_send": True}
        self.assertTrue(RecognitionGuard().assess(result, 4)["auto_send"])

    def test_missing_reason_still_preserves_an_explicit_hold(self):
        result = {"text": "hello there", "auto_send": False}
        self.assertFalse(RecognitionGuard().assess(result, 4)["auto_send"])

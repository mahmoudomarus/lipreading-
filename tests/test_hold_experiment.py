import unittest

from recognition_guard import RecognitionGuard
from turn_taking import Utterances


class HoldExperimentTests(unittest.TestCase):
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

    def test_propagated_draft_preserves_disagreement_hold_with_flag_off(self):
        result = self.assembled()
        self.assertFalse(result["auto_send"])
        self.assertEqual(result["draft_text"], "no")
        self.assertFalse(RecognitionGuard().assess(result, 4)["auto_send"])
        changed = RecognitionGuard(preserve_holds=True).assess(result, 4)
        self.assertFalse(changed["auto_send"])
        self.assertEqual(changed["review_reason"], result["review_reason"])

    def test_opt_in_does_not_invent_holds_for_previously_accepted_text(self):
        result = {"text": "please call maya in five minutes", "auto_send": True}
        self.assertEqual(
            RecognitionGuard().assess(result, 4),
            RecognitionGuard(preserve_holds=True).assess(result, 4),
        )

    def test_missing_reason_still_preserves_an_explicit_hold(self):
        result = {"text": "hello there", "auto_send": False}
        self.assertFalse(RecognitionGuard(preserve_holds=True).assess(result, 4)["auto_send"])

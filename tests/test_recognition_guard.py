import unittest

import numpy as np

from engine import LipReader, NoSpeech, mouth_motion
from recognition_guard import RecognitionGuard, review_reason


class GuardTests(unittest.TestCase):
    def test_repeated_filler_is_held_without_a_phrase_blacklist(self):
        self.assertIsNotNone(review_reason("I WOULD LIKE TO EXPLAIN THIS TO YOU " * 4))
        self.assertIsNone(review_reason("Can you explain how a bicycle stays upright?"))

    def test_empty_visual_draft_never_calls_the_language_decoder(self):
        reader = LipReader.__new__(LipReader)
        with self.assertRaises(NoSpeech):
            reader.refine({"metadata": {"text": ""}})

    def test_decoder_expansion_is_held(self):
        self.assertIsNotNone(
            review_reason(
                "Let me explain a long story that we never actually saw at all",
                draft="HELLO",
                duration=3,
            )
        )
        self.assertIsNone(
            review_reason("Hello how are you today", draft="HELO HOW ARE YU TODAY", duration=3)
        )

    def test_implausible_word_rate_is_held(self):
        self.assertIsNotNone(
            review_reason(
                "one two three four five six seven eight nine ten eleven twelve", duration=1
            )
        )

    def test_recent_long_repeated_reading_is_not_resent_but_short_answers_can_repeat(self):
        guard = RecognitionGuard()
        entry = {
            "text": "Can you explain how a bicycle stays upright?",
            "draft_text": "Can you explain how a bicycle stays upright?",
            "duration": 4,
        }
        self.assertTrue(guard.assess(entry, 5)["auto_send"])
        self.assertFalse(guard.assess(entry, 12)["auto_send"])
        self.assertTrue(guard.assess(entry, 70)["auto_send"])
        for timestamp in (71, 72):
            self.assertTrue(
                guard.assess({"text": "Yes please", "duration": 1}, timestamp)["auto_send"]
            )

    def test_uniform_exposure_changes_are_not_lip_motion(self):
        frames = np.stack([np.full((96, 96), v, np.uint8) for v in [100, 110, 98, 105]])
        self.assertAlmostEqual(mouth_motion(frames), 0)
        frames[1, 30:65, 25:65] += 20
        self.assertGreater(mouth_motion(frames), 0.65)

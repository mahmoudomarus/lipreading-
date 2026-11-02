import unittest

from support import RuntimeTestCase

import commands
from commands import DEFAULT_PHRASES, clean_phrases, correct_terms, lip_shapes, match


class CommandMatchTests(unittest.TestCase):
    def test_look_alike_words_share_lip_shapes(self):
        self.assertEqual(lip_shapes("heaven"), lip_shapes("seven"))
        self.assertEqual(lip_shapes("bat"), lip_shapes("mat"))

    def test_close_misreads_snap_and_unrelated_readings_do_not(self):
        snapped = {
            "SAID A TIMER FOR FIVE MINUTES": "Set a timer for five minutes",
            "SO MY NOTES": "Show my notes",
            "I KNEW HELP": "I need help",
            "THANKS YOU": "Thank you",
        }
        for reading, phrase in snapped.items():
            self.assertEqual(match([reading], DEFAULT_PHRASES)[0], phrase, reading)
        for reading in ["THE SUNRISE WOULD BE TOO SOON", "IT'S A HOMEMADE FRIEND", "SO", "I"]:
            self.assertIsNone(match([reading], DEFAULT_PHRASES), reading)

    def test_alternative_readings_can_supply_the_match(self):
        found = match(["THE SUNRISE", "SHOW MY NOTES"], DEFAULT_PHRASES)
        self.assertEqual(found[0], "Show my notes")

    def test_ambiguous_near_ties_are_held(self):
        self.assertIsNone(
            match(["SET A TIMER FOR"], ["Set a timer for one", "Set a timer for won"])
        )

    def test_apply_marks_heard_text_and_holds_misses(self):
        hit = commands.apply({"text": "SO MY NOTES", "auto_send": False}, ["Show my notes"])
        self.assertEqual(
            (hit["text"], hit["heard"], hit["auto_send"]), ("Show my notes", "SO MY NOTES", True)
        )
        miss = commands.apply({"text": "BANANA", "auto_send": True}, ["Show my notes"])
        self.assertFalse(miss["auto_send"])

    def test_phrase_lists_are_cleaned_and_bounded(self):
        self.assertEqual(
            clean_phrases(["  Yes ", "yes", "", "Call  my wife"]), ["Yes", "Call my wife"]
        )
        for bad in ("Yes", ["x" * 121], ["a"] * 61, [3]):
            with self.assertRaises(ValueError):
                clean_phrases(bad)


class NameCorrectionTests(unittest.TestCase):
    terms = ["Trader Joe's", "Whole Foods", "Maya", "Omar"]

    def test_lip_reading_misses_of_saved_names_are_corrected(self):
        cases = {
            "HELLO I'M HEADING TO TRAITOR JONES TO BUY GROCERIES": "HELLO I'M HEADING TO Trader Joe's TO BUY GROCERIES",
            "TRAINER JONES": "Trader Joe's",
            "I'M GOING TO DRAKE JONES TONIGHT": "I'M GOING TO Trader Joe's TONIGHT",
            "LET'S GO TO HOLE FOODS": "LET'S GO TO Whole Foods",
            "TELL OMER": "TELL Omar",
        }
        for reading, corrected in cases.items():
            self.assertEqual(correct_terms(reading, self.terms)[0], corrected, reading)

    def test_ordinary_words_are_left_alone(self):
        for reading in ["MY NAME IS MAYOR", "I WENT TO TRADE SHOWS", "OH MY", "I'M NOT SURE"]:
            self.assertEqual(correct_terms(reading, self.terms), (reading, []), reading)


class PhraseRouteTests(RuntimeTestCase):
    def test_vocabulary_defaults_empty_saves_and_requires_access(self):
        self.assertEqual(self.client.get("/api/vocabulary").status_code, 401)
        headers = {"Authorization": "Bearer " + self.runtime.token}
        self.assertEqual(self.client.get("/api/vocabulary", headers=headers).json()["terms"], [])
        saved = self.client.post(
            "/api/vocabulary", headers=headers, json={"terms": ["Trader Joe's"]}
        )
        self.assertEqual(saved.json()["terms"], ["Trader Joe's"])

    def test_phrases_default_save_and_require_access(self):
        self.assertEqual(self.client.get("/api/phrases").status_code, 401)
        headers = {"Authorization": "Bearer " + self.runtime.token}
        self.assertEqual(
            self.client.get("/api/phrases", headers=headers).json()["phrases"], DEFAULT_PHRASES
        )
        saved = self.client.post(
            "/api/phrases", headers=headers, json={"phrases": ["Call my wife"]}
        )
        self.assertEqual(saved.json()["phrases"], ["Call my wife"])
        self.assertEqual(
            self.client.get("/api/phrases", headers=headers).json()["phrases"], ["Call my wife"]
        )
        self.assertEqual(
            self.client.post("/api/phrases", headers=headers, json={"phrases": "nope"}).status_code,
            400,
        )

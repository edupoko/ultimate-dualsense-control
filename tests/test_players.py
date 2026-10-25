import unittest

from dualsense_ultimate_control.players import NO_PLAYER, PLAYER_PATTERNS, pattern_for, player_number


class PlayerPatternsTest(unittest.TestCase):
    def test_patterns_match_the_console(self):
        shown = ["".join("x" if on else "-" for on in pattern) for pattern in PLAYER_PATTERNS]
        self.assertEqual(shown, ["--x--", "-x-x-", "x-x-x", "xx-xx", "xxxxx"])

    def test_number_round_trip(self):
        for number in range(1, 6):
            self.assertEqual(player_number(pattern_for(number)), number)

    def test_no_leds_or_custom_pattern_is_no_player(self):
        self.assertIsNone(player_number(NO_PLAYER))
        self.assertIsNone(player_number([True, False, False, False, False]))


if __name__ == "__main__":
    unittest.main()

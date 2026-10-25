import unittest

from dualsense_led.ds5 import triggers
from dualsense_led.ds5.reports import TRIGGER_EFFECT_SIZE


class TriggerEffectsTest(unittest.TestCase):
    def test_every_effect_is_eleven_bytes(self):
        for name, make in triggers.EFFECTS.items():
            for position in (-3, 0, 5, 9, 20):
                for strength in (0, 1, 8, 99):
                    self.assertEqual(len(make(position, strength)), TRIGGER_EFFECT_SIZE, name)

    def test_off(self):
        self.assertEqual(triggers.off()[0], triggers.MODE_OFF)
        self.assertEqual(sum(triggers.off()[1:]), 0)

    def test_resistance_zones_and_strength(self):
        data = triggers.resistance(8, 3)
        # Zonas 8 e 9 ativas, força 3 (valor 2) em 3 bits cada.
        self.assertEqual(data[0], triggers.MODE_FEEDBACK)
        self.assertEqual(int.from_bytes(data[1:3], "little"), 0b11_0000_0000)
        self.assertEqual(int.from_bytes(data[3:7], "little"), (2 << 24) | (2 << 27))

    def test_weapon_start_is_clamped(self):
        data = triggers.weapon(0, 5)
        self.assertEqual(int.from_bytes(data[1:3], "little"), (1 << 2) | (1 << 3))
        self.assertEqual(data[3], 4)

    def test_vibration_frequency_byte(self):
        self.assertEqual(triggers.vibration(0, 1)[9], 30)


if __name__ == "__main__":
    unittest.main()

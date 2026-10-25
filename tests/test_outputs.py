import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from test_sysfs import make_led, write_uevent  # noqa: F401  (mantém o mesmo ambiente dos outros testes)

from dualsense_ultimate_control.ds5 import triggers
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.testpanel.outputs import OutputPanel


class FakeDevice:
    def __init__(self):
        self.sent = []

    def send_output(self, **fields):
        self.sent.append(fields)


class OutputPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        service = LedService(root / "s.json", root / "leds", bluetooth_probe=lambda known: [])
        self.panel = OutputPanel(service)
        self.panel.mic_meter.start = lambda: None  # sem áudio nos testes
        self.device = FakeDevice()
        self.panel.set_device(self.device)

    def test_sliders_send_rumble(self):
        self.panel._heavy.setValue(100)
        self.assertEqual(self.device.sent[-1], {"rumble": (100, 0)})

    def test_trigger_effect_is_sent(self):
        self.panel._left._effect.setCurrentIndex(1)  # resistência
        self.assertEqual(self.device.sent[-1]["left_trigger"][0], triggers.MODE_FEEDBACK)

    def test_restore_on_release(self):
        self.panel._heavy.setValue(100)
        self.panel.set_device(None)
        self.assertEqual(
            self.device.sent[-1],
            {"rumble": (0, 0), "left_trigger": triggers.OFF, "right_trigger": triggers.OFF},
        )
        self.assertEqual(self.panel._heavy.value(), 0)

    def test_nothing_sent_on_release_if_untouched(self):
        self.panel.set_device(None)
        self.assertEqual(self.device.sent, [])


if __name__ == "__main__":
    unittest.main()

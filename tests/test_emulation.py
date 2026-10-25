import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.emulation import EmulationProcess
from dualsense_ultimate_control.service import LedService
from dualsense_ultimate_control.settings import load_settings
from dualsense_ultimate_control.widgets import EmulationRow
from test_sysfs import make_led, write_uevent


def wait_until(condition, timeout_ms=5000):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: condition() and loop.quit())
    timer.start(20)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return condition()


class EmulationProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def fake(self, code):
        emulation = EmulationProcess(sys.executable, ["-c", code], service_probe=lambda: False)
        self.addCleanup(emulation.stop)
        return emulation

    def test_start_and_stop(self):
        emulation = self.fake("import time; time.sleep(30)")
        changes = []
        emulation.changed.connect(lambda: changes.append(emulation.running))
        failures = []
        emulation.failed.connect(failures.append)
        emulation.set_running(True)
        self.assertTrue(emulation.running)
        emulation.set_running(False)
        self.assertFalse(emulation.running)
        self.assertEqual(changes, [True, False])
        self.assertEqual(failures, [])

    def test_does_not_start_while_the_systemd_service_runs(self):
        emulation = EmulationProcess(sys.executable, ["-c", "import time; time.sleep(30)"], service_probe=lambda: True)
        self.addCleanup(emulation.stop)
        emulation.start()
        self.assertFalse(emulation.running)

    def test_start_twice_keeps_one_process(self):
        emulation = self.fake("import time; time.sleep(30)")
        emulation.start()
        first = emulation._process
        emulation.start()
        self.assertIs(emulation._process, first)

    def test_unexpected_exit_reports_last_log_line(self):
        emulation = self.fake("import sys; print('sem permissão no uinput', file=sys.stderr); sys.exit(1)")
        failures = []
        emulation.failed.connect(failures.append)
        emulation.start()
        self.assertTrue(wait_until(lambda: not emulation.running))
        self.assertEqual(failures, ["sem permissão no uinput"])

    def test_missing_program_fails(self):
        emulation = EmulationProcess("/nao/existe/python", [], service_probe=lambda: False)
        failures = []
        emulation.failed.connect(failures.append)
        emulation.start()
        self.assertTrue(wait_until(lambda: not emulation.running))
        self.assertEqual(len(failures), 1)

    def service(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for number, mac in ((1, "14:3a:9a:74:05:eb"), (2, "bc:c7:46:32:3c:58")):
            device = f"0003:054C:0CE6.00{number}0"
            make_led(root, f"input{number}:rgb:indicator", device, ("brightness", "multi_intensity"))
            for player in range(1, 6):
                make_led(root, f"input{number}:white:player-{player}", device)
            write_uevent(root, device, mac, "0003")
        service = LedService(root / "settings.json", root / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        service.refresh()
        return service, root

    def test_row_follows_process(self):
        service, _ = self.service()
        emulation = self.fake("import time; time.sleep(30)")
        row = EmulationRow(service, emulation)
        row._switch.click()
        self.assertTrue(emulation.running)
        self.assertTrue(row._switch.isChecked())
        emulation.stop()
        self.assertTrue(row._switch.isChecked())  # a escolha do controle segue salva
        row._switch.click()
        self.assertFalse(row._switch.isChecked())
        self.assertFalse(emulation.running)

    def test_row_saves_the_choice_per_controller(self):
        service, root = self.service()
        emulation = self.fake("import time; time.sleep(30)")
        row = EmulationRow(service, emulation)
        first = service.selected_uid
        row._switch.click()
        self.assertEqual(load_settings(root / "settings.json").emulation, [first])
        # Parar sem ser pelo interruptor (ex.: ao sair do app) não muda a escolha salva.
        emulation.stop()
        self.assertEqual(load_settings(root / "settings.json").emulation, [first])
        # Outra aba é outro controle: começa desligado e não mexe no primeiro.
        other = next(c.name for c in service.controllers if c.uid != first)
        service.select_controller(other)
        self.assertFalse(row._switch.isChecked())
        row._switch.click()
        self.assertEqual(load_settings(root / "settings.json").emulation, sorted([first, service.selected_uid]))
        self.assertTrue(emulation.running)
        row._switch.click()  # desliga só o segundo: o processo segue por causa do primeiro
        self.assertEqual(load_settings(root / "settings.json").emulation, [first])
        self.assertTrue(emulation.running)
        service.select_controller(next(c.name for c in service.controllers if c.uid == first))
        row._switch.click()
        self.assertEqual(load_settings(root / "settings.json").emulation, [])
        self.assertFalse(emulation.running)

    def test_row_is_disabled_without_a_controller(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = LedService(Path(tmp.name) / "s.json", Path(tmp.name) / "leds", steam_probe=set, bluetooth_probe=lambda k: [])
        service.refresh()
        row = EmulationRow(service, self.fake("pass"))
        self.assertFalse(row.isEnabled())

    def test_clearing_all_choices(self):
        service, _ = self.service()
        service.set_emulation_for("AA:BB", True)
        self.assertTrue(service.emulation_for("aa:bb"))
        service.set_emulation(False)
        self.assertFalse(service.emulation)


if __name__ == "__main__":
    unittest.main()

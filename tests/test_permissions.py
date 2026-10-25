import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control.permissions import RULE_SOURCE, RuleInstaller, install_arguments, rule_installed


class RuleInstalledTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = Path(self._tmp.name) / "70-dualsense-ultimate-control.rules"

    def test_missing_rule(self):
        self.assertFalse(rule_installed(self.target))

    def test_outdated_rule(self):
        self.target.write_text("# versão antiga\n")
        self.assertFalse(rule_installed(self.target))

    def test_current_rule(self):
        self.target.write_bytes(RULE_SOURCE.read_bytes())
        self.assertTrue(rule_installed(self.target))

    def test_install_arguments_pass_paths_as_arguments(self):
        args = install_arguments()
        self.assertEqual(args[:2], ["/bin/sh", "-c"])
        self.assertEqual(args[-1], "/etc/udev/rules.d/70-dualsense-ultimate-control.rules")
        self.assertEqual(Path(args[-2]), RULE_SOURCE)


class RuleInstallerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_installer(self, program: str) -> tuple[bool, str]:
        installer = RuleInstaller(program)
        loop = QEventLoop()
        result = []
        installer.finished.connect(lambda ok, message: (result.append((ok, message)), loop.quit()))
        QTimer.singleShot(5000, loop.quit)
        installer.start()
        if not result:
            loop.exec()
        self.assertFalse(installer.running)
        return result[0]

    def test_success(self):
        # "true" ignora os argumentos e sai com 0, simulando o pkexec com senha aceita.
        ok, _ = self.run_installer("true")
        self.assertTrue(ok)

    def test_failure(self):
        ok, message = self.run_installer("false")
        self.assertFalse(ok)
        self.assertIn("Falha", message)

    def test_missing_program(self):
        ok, message = self.run_installer("programa-que-nao-existe")
        self.assertFalse(ok)
        self.assertIn("não encontrado", message)


if __name__ == "__main__":
    unittest.main()

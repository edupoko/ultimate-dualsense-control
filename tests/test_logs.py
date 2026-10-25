import logging
import logging.handlers
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualsense_ultimate_control import i18n, logs
from dualsense_ultimate_control.logview import FILTER_PROBLEMS, LogWindow


class LogsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        self.addCleanup(self._restore, saved_handlers, saved_level)

    @staticmethod
    def _restore(handlers, level):
        root = logging.getLogger()
        for handler in list(root.handlers):
            if handler not in handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(level)


class FileLoggingTest(LogsTestCase):
    def test_records_go_to_the_log_file_in_the_state_folder(self):
        path = logs.setup_logging(install_hooks=False)
        self.assertEqual(path, Path(self._tmp.name) / "dualsense-ultimate-control" / "dualsense-ultimate-control.log")
        logging.getLogger("dualsense_ultimate_control.teste").info("controle conectado")
        text = path.read_text()
        self.assertRegex(text, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d INFO dualsense_ultimate_control.teste: controle conectado$")

    def test_calling_setup_twice_does_not_duplicate_lines(self):
        logs.setup_logging(install_hooks=False)
        path = logs.setup_logging(install_hooks=False)
        logging.getLogger("x").warning("uma vez só")
        self.assertEqual(path.read_text().count("uma vez só"), 1)

    def test_file_rotates_and_keeps_a_limited_history(self):
        logs.setup_logging(install_hooks=False)
        handler = next(h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        self.assertEqual((handler.maxBytes, handler.backupCount), (logs.MAX_BYTES, logs.BACKUPS))

    def test_debug_level_is_optional(self):
        logs.setup_logging(logging.INFO, install_hooks=False)
        logging.getLogger("x").debug("detalhe")
        self.assertNotIn("detalhe", logs.log_path().read_text())
        logs.setup_logging(logging.DEBUG, install_hooks=False)
        logging.getLogger("x").debug("detalhe")
        self.assertIn("detalhe", logs.log_path().read_text())

    def test_uncaught_exception_is_logged_with_its_traceback(self):
        logs.setup_logging(install_hooks=False)
        try:
            raise ValueError("quebrou")
        except ValueError:
            logs._log_uncaught_exception(*sys.exc_info())
        text = logs.log_path().read_text()
        self.assertIn("CRITICAL dualsense_ultimate_control: Erro não tratado", text)
        self.assertIn("ValueError: quebrou", text)


class QtMessageTest(unittest.TestCase):
    def test_levels_follow_the_qt_severity(self):
        from PySide6.QtCore import QtMsgType
        self.assertEqual(logs.qt_level(QtMsgType.QtInfoMsg, "x"), logging.INFO)
        self.assertEqual(logs.qt_level(QtMsgType.QtWarningMsg, "algo estranho"), logging.WARNING)
        self.assertEqual(logs.qt_level(QtMsgType.QtCriticalMsg, "x"), logging.ERROR)
        self.assertEqual(logs.qt_level(QtMsgType.QtFatalMsg, "x"), logging.CRITICAL)

    def test_known_harmless_warnings_do_not_show_up_as_problems(self):
        from PySide6.QtCore import QtMsgType
        self.assertEqual(logs.qt_level(QtMsgType.QtWarningMsg, "Could not find any platform plugin"), logging.DEBUG)
        self.assertEqual(logs.qt_level(QtMsgType.QtWarningMsg, 'Icon theme "gnome" not found.'), logging.DEBUG)


class ReadingTest(LogsTestCase):
    def test_read_log_of_a_missing_file_is_empty(self):
        self.assertEqual(logs.read_log(), "")

    def test_read_log_returns_only_the_end_and_starts_on_a_whole_line(self):
        path = logs.log_dir() / logs.LOG_NAME
        path.parent.mkdir(parents=True)
        path.write_text("".join(f"2026-10-25 02:00:{n:02d} INFO a: linha {n}\n" for n in range(60)))
        text = logs.read_log(max_bytes=200, path=path)
        self.assertLess(len(text), 200)
        self.assertTrue(text.startswith("2026-"))
        self.assertTrue(text.endswith("linha 59\n"))

    def test_problems_only_keeps_warnings_errors_and_their_tracebacks(self):
        text = (
            "2026-10-25 02:00:00 INFO a: tudo bem\n"
            "2026-10-25 02:00:01 WARNING a: atenção\n"
            "2026-10-25 02:00:02 INFO a: de novo\n"
            "2026-10-25 02:00:03 ERROR a: falhou\n"
            "Traceback (most recent call last):\n"
            "  File \"x.py\", line 1\n"
            "ValueError: x\n"
            "2026-10-25 02:00:04 INFO a: fim\n"
        )
        kept = logs.problems_only(text)
        self.assertEqual(kept.count("\n"), 5)
        self.assertIn("atenção", kept)
        self.assertIn("Traceback", kept)
        self.assertNotIn("tudo bem", kept)
        self.assertNotIn("fim", kept)
        self.assertEqual(logs.problems_only("2026-10-25 02:00:00 INFO a: ok\n"), "")

    def test_clear_log_empties_the_file(self):
        logs.setup_logging(install_hooks=False)
        logging.getLogger("x").info("algo")
        logs.clear_log()
        self.assertEqual(logs.read_log(), "")
        logging.getLogger("x").info("depois")
        self.assertIn("depois", logs.read_log())


class LogWindowTest(LogsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.addCleanup(i18n.set_language, "pt")
        logs.setup_logging(install_hooks=False)
        logging.getLogger("a").info("controle conectado")
        logging.getLogger("a").warning("sem permissão")
        self.window = LogWindow()

    def text(self):
        return self.window._view.toPlainText()

    def test_shows_the_log(self):
        self.assertIn("controle conectado", self.text())
        self.assertIn("sem permissão", self.text())

    def test_filter_shows_only_problems(self):
        self.window._filter.setCurrentIndex(self.window._filter.findData(FILTER_PROBLEMS))
        self.assertNotIn("controle conectado", self.text())
        self.assertIn("sem permissão", self.text())

    def test_picks_up_new_lines_on_refresh(self):
        logging.getLogger("a").error("novo erro")
        self.window.refresh()
        self.assertIn("novo erro", self.text())

    def test_empty_log_shows_a_message_in_the_current_language(self):
        logs.clear_log()
        self.window.refresh()
        self.assertEqual(self.text(), "(sem registros)")
        i18n.set_language("en")
        self.window.refresh()
        self.assertEqual(self.window._filter.itemText(0), "Everything")

    def test_clear_button_action_empties_the_view(self):
        self.window._clear()
        self.assertEqual(self.text(), "(sem registros)")

    def test_copy_puts_the_visible_text_on_the_clipboard(self):
        self.window._copy()
        self.assertIn("controle conectado", QApplication.clipboard().text())


class CommandLineTest(LogsTestCase):
    def test_logs_option_prints_the_path_and_the_end_of_the_file(self):
        logs.setup_logging(install_hooks=False)
        logging.getLogger("a").info("linha de teste")
        env = dict(os.environ, XDG_STATE_HOME=self._tmp.name)
        result = subprocess.run(
            [sys.executable, "-m", "dualsense_ultimate_control", "--logs"], env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(logs.log_path()), result.stdout)
        self.assertIn("linha de teste", result.stdout)


if __name__ == "__main__":
    unittest.main()

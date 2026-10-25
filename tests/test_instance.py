import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = (
    "import dualsense_led.__main__ as entry; "
    "print('principal' if entry._acquire_instance_lock() else 'secundaria')"
)


class SingleInstanceLockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.env = dict(os.environ, XDG_RUNTIME_DIR=self._tmp.name, DUALSENSE_LED_INSTANCE="dsled-unit-test")

    def check(self) -> str:
        result = subprocess.run([sys.executable, "-c", CHECK], env=self.env, capture_output=True, text=True, timeout=60)
        return result.stdout.strip()

    def test_only_the_first_process_becomes_the_main_instance(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", CHECK + "; import sys, time; sys.stdout.flush(); time.sleep(30)"],
            env=self.env, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "principal")
        self.assertEqual(self.check(), "secundaria")

    def test_lock_is_released_when_the_process_ends(self):
        self.assertEqual(self.check(), "principal")
        self.assertEqual(self.check(), "principal")
        self.assertTrue((Path(self._tmp.name) / "dsled-unit-test.lock").exists())


if __name__ == "__main__":
    unittest.main()

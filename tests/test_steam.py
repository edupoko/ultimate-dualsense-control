import tempfile
import unittest
from pathlib import Path

from dualsense_ultimate_control.steam import hidraw_held_by_steam


def fake_process(proc: Path, pid: int, comm: str, targets: list[str]) -> None:
    entry = proc / str(pid)
    (entry / "fd").mkdir(parents=True)
    (entry / "comm").write_text(comm + "\n")
    for number, target in enumerate(targets):
        (entry / "fd" / str(number)).symlink_to(target)


class HidrawHeldBySteamTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name)

    def test_finds_hidraw_opened_by_steam(self):
        fake_process(self.proc, 4170, "steam", ["/dev/hidraw10", "/dev/null", "/dev/hidraw3"])
        self.assertEqual(hidraw_held_by_steam(self.proc), {"/dev/hidraw10", "/dev/hidraw3"})

    def test_ignores_other_processes(self):
        fake_process(self.proc, 10, "steamwebhelper", ["/dev/hidraw10"])
        fake_process(self.proc, 11, "game", ["/dev/hidraw11"])
        (self.proc / "self").mkdir()
        self.assertEqual(hidraw_held_by_steam(self.proc), set())

    def test_missing_proc_is_empty(self):
        self.assertEqual(hidraw_held_by_steam(self.proc / "nope"), set())


if __name__ == "__main__":
    unittest.main()

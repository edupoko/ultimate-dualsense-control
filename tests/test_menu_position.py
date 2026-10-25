import unittest

from PySide6.QtCore import QPoint, QRect, QSize

from dualsense_led.widgets import tray_corner_position

SCREEN = QRect(0, 0, 1920, 1080)
SIZE = QSize(470, 400)


class MenuPositionTest(unittest.TestCase):
    def position(self, available: QRect) -> QPoint:
        return tray_corner_position(SIZE, SCREEN, available, margin=8)

    def test_bottom_panel_opens_bottom_right(self):
        self.assertEqual(self.position(QRect(0, 0, 1920, 1036)), QPoint(1920 - 470 - 8, 1036 - 400 - 8))

    def test_top_panel_opens_top_right(self):
        self.assertEqual(self.position(QRect(0, 44, 1920, 1036)), QPoint(1920 - 470 - 8, 44 + 8))

    def test_left_panel_opens_bottom_left(self):
        self.assertEqual(self.position(QRect(60, 0, 1860, 1080)), QPoint(60 + 8, 1080 - 400 - 8))

    def test_right_panel_opens_beside_it(self):
        self.assertEqual(self.position(QRect(0, 0, 1860, 1080)), QPoint(1860 - 470 - 8, 1080 - 400 - 8))

    def test_second_monitor_offset(self):
        screen = QRect(1920, 0, 2560, 1440)
        available = QRect(1920, 0, 2560, 1396)
        self.assertEqual(tray_corner_position(SIZE, screen, available, margin=8),
                         QPoint(1920 + 2560 - 470 - 8, 1396 - 400 - 8))


if __name__ == "__main__":
    unittest.main()

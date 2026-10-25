import json
import unittest
from types import SimpleNamespace

from dualsense_ultimate_control.bluetooth import unregistered_dualsense


def bluez(*devices):
    objects = {f"/org/bluez/hci0/dev_{i}": {"org.bluez.Device1": device} for i, device in enumerate(devices)}
    output = json.dumps({"type": "a{oa{sa{sv}}}", "data": [objects]})
    return lambda *args, **kwargs: SimpleNamespace(stdout=output)


def device(address, modalias, connected):
    return {
        "Address": {"type": "s", "data": address},
        "Modalias": {"type": "s", "data": modalias},
        "Connected": {"type": "b", "data": connected},
    }


class UnregisteredDualSenseTest(unittest.TestCase):
    def test_connected_dualsense_missing_from_the_system(self):
        run = bluez(
            device("BC:C7:46:32:3C:58", "usb:v054Cp0CE6d0100", True),
            device("14:3A:9A:74:05:EB", "usb:v054Cp0CE6d0100", True),
        )
        self.assertEqual(unregistered_dualsense(["14:3a:9a:74:05:eb"], run), ["bc:c7:46:32:3c:58"])

    def test_ignores_disconnected_other_products_and_edge_is_included(self):
        run = bluez(
            device("AA:00:00:00:00:01", "usb:v054Cp0CE6d0100", False),
            device("AA:00:00:00:00:02", "usb:v054Cp09CCd0100", True),  # DualShock 4
            device("AA:00:00:00:00:03", "bluetooth:v05D6p000Ad0240", True),
            device("AA:00:00:00:00:04", "usb:v054Cp0DF2d0100", True),  # DualSense Edge
        )
        self.assertEqual(unregistered_dualsense([], run), ["aa:00:00:00:00:04"])

    def test_bluez_unavailable_is_empty(self):
        def broken(*args, **kwargs):
            raise OSError("busctl ausente")
        self.assertEqual(unregistered_dualsense([], broken), [])
        self.assertEqual(unregistered_dualsense([], lambda *a, **k: SimpleNamespace(stdout="")), [])


if __name__ == "__main__":
    unittest.main()

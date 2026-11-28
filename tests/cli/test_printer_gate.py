"""Tests for the wait-for-a-label-printer gate."""

import unittest
from unittest import mock

from ibp_printing import Discovery, PrinterCandidate, PrintQueue, UsbDevice
from ibp_printing import log as log_module
from ibp_printing.printers import LABELWRITER_450_TURBO, PM2411BT, SP310

from shippy.cli import printer_gate


class FakeConsole:
    """Records what the gate would have printed."""

    def __init__(self):
        self.lines = []

    def __call__(self, text="", **_kwargs):
        self.lines.append(text)


def scripted(values):
    """A callable returning the given values in order, then the last forever."""
    values = list(values)

    def call(*_args):
        return values.pop(0) if len(values) > 1 else values[0]

    return call


class WaitForPrinterTests(unittest.TestCase):
    """wait_for_printer()."""

    def test_printer_already_ready_is_silent(self):
        say = FakeConsole()
        ready = printer_gate.wait_for_printer(
            find_printers=lambda: ["BOB"],
            wait_for_continue=lambda _t: self.fail("should not wait"),
            say=say,
        )
        self.assertTrue(ready)
        self.assertEqual(say.lines, [])

    def test_continues_by_itself_when_printer_appears(self):
        say = FakeConsole()
        waits = []

        def wait(timeout_s):
            waits.append(timeout_s)
            return False

        ready = printer_gate.wait_for_printer(
            find_printers=scripted([[], [], ["BETTY"]]),
            wait_for_continue=wait,
            say=say,
            interval_s=2.0,
        )
        self.assertTrue(ready)
        self.assertEqual(waits, [2.0, 2.0])
        self.assertTrue(any("NO LABEL PRINTER FOUND" in line for line in say.lines))
        self.assertIn("Label printer ready: BETTY", say.lines[-1])

    def test_only_repeated_polls_are_quiet(self):
        quiet_flags = []

        def find():
            # quiet() sets a context flag; record it for each check.
            quiet_flags.append(
                log_module._QUIET.get()
            )  # pylint: disable=protected-access
            return ["BOB"] if len(quiet_flags) == 3 else []

        ready = printer_gate.wait_for_printer(
            find_printers=find,
            wait_for_continue=lambda _t: False,
            say=FakeConsole(),
            when="before purchase",
        )
        self.assertTrue(ready)
        self.assertEqual(quiet_flags, [False, True, True])

    def test_enter_continues_without_printer(self):
        say = FakeConsole()
        ready = printer_gate.wait_for_printer(
            find_printers=lambda: [],
            wait_for_continue=scripted([False, True]),
            say=say,
        )
        self.assertFalse(ready)
        self.assertIn("Continuing without a label printer", say.lines[-1])
        self.assertTrue(any("to-print" in line for line in say.lines))

    def test_ctrl_c_propagates(self):
        def interrupt(_timeout_s):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            printer_gate.wait_for_printer(
                find_printers=lambda: [],
                wait_for_continue=interrupt,
                say=FakeConsole(),
            )


class UsablePrinterNamesTests(unittest.TestCase):
    """usable_printer_names()."""

    def test_discovery_failure_counts_as_no_printer(self):
        original = printer_gate.discover

        def broken():
            raise OSError("WMI unavailable")

        printer_gate.discover = broken
        try:
            with self.assertLogs(printer_gate.logger.name, "ERROR"):
                self.assertEqual(printer_gate.usable_printer_names(), [])
        finally:
            printer_gate.discover = original


def plugged_in(name: str, vid_pid: str) -> PrinterCandidate:
    """A usable print queue whose USB device is plugged in."""
    device = UsbDevice(
        device_id=f"USB\\VID_{vid_pid[:4]}&PID_{vid_pid[5:]}\\1", vid_pid=vid_pid
    )
    return PrinterCandidate(PrintQueue(name=name), vid_pid, (device,))


class ShippingPrintersOnlyTests(unittest.TestCase):
    """Only printers for 4x6 postage let a purchase go ahead."""

    def names_with(self, *candidates):
        """usable_printer_names() with these printers plugged in."""
        found = Discovery(candidates=list(candidates))
        with mock.patch.object(printer_gate, "discover", return_value=found):
            return printer_gate.usable_printer_names()

    def test_package_label_printers_alone_count_as_no_printer(self):
        names = self.names_with(
            plugged_in("SP310 Package", SP310.vid_pid),
            plugged_in("DYMO LabelWriter", LABELWRITER_450_TURBO.vid_pid),
        )
        self.assertEqual(names, [])

    def test_shipping_and_unknown_printers_count(self):
        names = self.names_with(
            plugged_in("SP310 Package", SP310.vid_pid),
            plugged_in("BOB", PM2411BT.vid_pid),
            plugged_in("Label printer 1234:5678", "1234:5678"),
        )
        self.assertEqual(sorted(names), ["BOB", "Label printer 1234:5678"])

    def test_only_a_package_printer_shows_the_no_printer_prompt(self):
        say = FakeConsole()
        found = Discovery(candidates=[plugged_in("SP310 Package", SP310.vid_pid)])
        with mock.patch.object(printer_gate, "discover", return_value=found):
            ready = printer_gate.wait_for_printer(
                wait_for_continue=lambda _t: True, say=say
            )
        self.assertFalse(ready)
        self.assertIn("  NO LABEL PRINTER FOUND  ", say.lines)


if __name__ == "__main__":
    unittest.main()

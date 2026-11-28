"""Tests for which printers postage may go to."""

from ibp_printing import PrinterCandidate, PrintQueue, UsbDevice
from ibp_printing.printers import LABELWRITER_450_TURBO, PM2411BT, SP310, parse_role

from shippy.core.printers import SHIPPING_LABEL, shipping_printers


def plugged_in(name: str, vid_pid: str) -> PrinterCandidate:
    """A print queue whose USB device is plugged in."""
    device = UsbDevice(
        device_id=f"USB\\VID_{vid_pid[:4]}&PID_{vid_pid[5:]}\\1", vid_pid=vid_pid
    )
    return PrinterCandidate(PrintQueue(name=name), vid_pid, (device,))


def test_package_label_printers_are_left_out_and_the_order_kept():
    candidates = [
        plugged_in("Label printer 1234:5678", "1234:5678"),
        plugged_in("SP310", SP310.vid_pid),
        plugged_in("BOB", PM2411BT.vid_pid),
        plugged_in("DYMO", LABELWRITER_450_TURBO.vid_pid),
    ]
    assert [c.name for c in shipping_printers(candidates)] == [
        "Label printer 1234:5678",
        "BOB",
    ]


def test_the_label_name_is_one_ibp_printing_knows():
    assert parse_role(SHIPPING_LABEL).value == "shipping"

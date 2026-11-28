"""Tests for the label journal glue both apps share."""

from types import SimpleNamespace
from unittest import mock

import ibp_printing
import pytest

from shippy.core import label_journal

ADDRESS = {
    "name": "Jane Doe #00012345",
    "street1": "Rt 2 Box 4400",
    "street2": "Bldg 4",
    "city": "Gatesville",
    "state": "TX",
    "zipcode": "76597",
}
SHIPMENT = SimpleNamespace(id="shp_1", tracking_code="9400")


def test_identity_joins_both_street_lines_like_the_label_watcher_expects():
    identity = label_journal.identity_for(ADDRESS)

    assert identity.recipient_key == ibp_printing.recipient_key(
        "Jane Doe #00012345", "Rt 2 Box 4400 Bldg 4", "Gatesville", "TX", "76597"
    )
    assert (
        identity.recipient_label == "Jane Doe #00012345, Rt 2 Box 4400, Gatesville, TX"
    )


def test_identity_is_the_same_for_an_easypost_style_address():
    """``zip`` instead of ``zipcode`` and a missing street2 change nothing."""
    easypost_style = {**ADDRESS, "zip": ADDRESS["zipcode"], "street2": None}
    del easypost_style["zipcode"]
    plain = {**ADDRESS, "street2": ""}

    assert label_journal.identity_for(easypost_style) == label_journal.identity_for(
        plain
    )


def test_tracking_ref_falls_back_to_the_shipment_id():
    assert label_journal.tracking_ref(SHIPMENT) == "9400"
    assert (
        label_journal.tracking_ref(SimpleNamespace(id="shp_2", tracking_code=None))
        == "shp_2"
    )


@pytest.fixture(name="journal")
def fixture_journal():
    """The ibp_printing module as the journal glue sees it, mocked."""
    with mock.patch("shippy.core.label_journal.ibp_printing") as fake:
        yield fake


@pytest.mark.parametrize("app", ["shippy", "shippy-gui"])
def test_record_purchase_tags_the_label_with_the_app(journal, app):
    identity = label_journal.identity_for(ADDRESS)

    record = label_journal.record_purchase(identity, SHIPMENT, app=app)

    assert record is journal.record_purchase.return_value
    journal.record_purchase.assert_called_once_with(
        recipient_key=identity.recipient_key,
        recipient_label=identity.recipient_label,
        tracking_code="9400",
        shipment_id="shp_1",
        app=app,
    )


def test_record_purchase_without_identity_journals_nothing(journal):
    assert label_journal.record_purchase(None, SHIPMENT, app="shippy") is None
    journal.record_purchase.assert_not_called()


def test_journal_failures_never_reach_the_shipment(journal):
    journal.record_purchase.side_effect = OSError("disk full")
    journal.update_status.side_effect = OSError("disk full")
    identity = label_journal.identity_for(ADDRESS)

    assert label_journal.record_purchase(identity, SHIPMENT, app="shippy") is None
    label_journal.update_status(SHIPMENT, label_journal.STATUS_PRINTED)


def test_update_status_passes_the_saved_file_as_text(journal, tmp_path):
    label_journal.update_status(
        SHIPMENT, label_journal.STATUS_QUEUED, file=tmp_path / "9400.png"
    )
    journal.update_status.assert_called_once_with(
        "9400", "queued", file=str(tmp_path / "9400.png")
    )


def test_retry_meta_names_the_app_and_when_postage_was_bought():
    identity = label_journal.identity_for(ADDRESS)
    record = SimpleNamespace(created=1700000000.0)

    meta = label_journal.retry_meta(identity, SHIPMENT, record, app="shippy-gui")

    assert meta == {
        "tracking_code": "9400",
        "shipment_id": "shp_1",
        "app": "shippy-gui",
        "created": 1700000000.0,
        "recipient_label": identity.recipient_label,
        "recipient_key": identity.recipient_key,
    }


def test_pending_labels_lets_the_caller_handle_a_journal_error(journal):
    journal.pending_labels.side_effect = OSError("locked")
    with pytest.raises(OSError):
        label_journal.pending_labels()

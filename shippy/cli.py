"""Run the application in a CLI."""

import argparse
import collections
import configparser
import contextlib
import datetime
import importlib.resources
import os
import pathlib
import subprocess
import sys
import typing

import easypost  # type: ignore
import googlemaps  # type: ignore
import questionary
import requests
from ibp_printing import (
    PrintError,
    PrintResult,
    configure_logging,
    discover,
    get_backend,
    print_to_first_available,
    save_for_retry,
)
from ibp_printing.diagnostics import build_report
from ibp_printing.log import get_logger
from PIL import Image

from . import console, labels, printer_gate, shipping
from .misc import build_tempfile, grab_png_from_url
from .models import Config
from .server import Server, ServerError, to_easypost_address

# How long to follow a spooled label job before giving up on knowing its outcome.
PRINT_TRACK_TIMEOUT_S = 30.0

# Name passed to ibp-printing so shippy gets its own printer log files.
LOG_APP_NAME = "shippy"
# diagnose-printer may run next to a shipping session; give it its own files.
DIAG_LOG_APP_NAME = "diag"

logger = get_logger("shippy")

# Shipping modes where the volunteer types the address (and so can fix it).
TYPED_ADDRESS_MODES = frozenset({"manual"})

# Volunteer-facing style for warnings and notices.
WARNING_STYLE = "fg:yellow"

# What to do when a label may not have printed. Unused labels are refunded
# automatically (a weekly job on the IBP server), so a second label is cheap.
CREATE_AGAIN_ADVICE = (
    "Check the printer. If no label came out, create it again; the unused one "
    "is refunded automatically."
)

# What to do after EasyPost or the IBP server failed for one package. A buy
# whose answer was lost may still have bought a label; that is left to the
# weekly refund job, with no check or extra prompt here (decided 2026-11-17).
NOT_BOUGHT_ADVICE = "No postage was bought. Try this package again."
MAYBE_BOUGHT_ADVICE = (
    "The purchase may not have completed. Try this package again; an unused "
    "label is refunded automatically."
)

# Failures reaching the IBP server: a 4xx it reported, or no usable answer.
SERVER_ERRORS = (ServerError, requests.RequestException)

T = typing.TypeVar("T")

# Outcomes whose raw value reads badly after "the printer queue reported".
OUTCOME_DETAILS = {
    "uncertain": "it could not be confirmed that the job reached the printer",
    "tracking_failed": "following the print job failed",
}


def build_unit_choices(units: list[dict]) -> dict[str, tuple[str, str]]:
    """Map uppercased display names to (jurisdiction, name) unit keys.

    Unit names are only unique per jurisdiction, so the jurisdiction is
    appended to the display name whenever a name is shared across
    jurisdictions.
    """
    name_counts = collections.Counter(unit["name"].upper() for unit in units)

    choices = {}
    for unit in units:
        key = unit["name"].upper()
        if name_counts[key] > 1:
            key = f"{key} ({unit['jurisdiction'].upper()})"
        choices[key] = (unit["jurisdiction"], unit["name"])

    return choices


def generate_addresses_bulk(config: Config):
    """Generate addresses for bulk shipping."""
    server = Server.from_config(config.ibp)

    recipient_name = fetch_until_ok(
        "Grabbing shipping settings from IBP server",
        lambda: server.shipping_settings()["unit_recipient_name"],
    )
    units = build_unit_choices(
        fetch_until_ok("Grabbing units list from IBP server", server.units)
    )

    while True:
        unit = console.query_unit(units)
        if unit is None:
            continue

        jurisdiction, name = units[unit]
        reference = shipping.unit_reference(jurisdiction, name)
        try:
            with console.task_message("Grabbing unit address from IBP server"):
                unit_data = server.unit(jurisdiction, name)
        except ServerError as exc:
            questionary.print(f"  {exc.detail}", style="fg:red")
            continue
        except requests.RequestException as exc:
            report_server_unreachable(exc)
            continue

        to_addr = to_easypost_address(recipient_name, unit_data)

        weight = console.query_weight()
        if weight is None:
            continue

        small_box = console.query_small_box(weight, shipping.BOX_QUESTION_MIN_LB)
        if small_box is None:
            continue

        yield to_addr, weight, small_box, reference


STALE_UNIT_AGE = datetime.timedelta(days=90)
"""How old an inmate's unit data can be before shippy warns it may be outdated."""

# The backend's ``inmate_status`` on a request address: whether it just
# re-checked the inmate with TDCJ. Older backends don't send it.
INMATE_CURRENT = "current"
"""Re-checked with TDCJ just now (or the data was fresh): ship normally."""
INMATE_NOT_LISTED = "not_listed"
"""TDCJ no longer lists the inmate (e.g. released): don't ship."""
INMATE_UNVERIFIED = "unverified"
"""TDCJ couldn't be reached; the stored unit was used."""


def fetch_request_address(
    server: Server, request_id: typing.Union[typing.Tuple[str, int, int], int]
) -> dict[str, typing.Any]:
    """Fetch the shipping address for a scanned request label."""
    if isinstance(request_id, tuple):
        # New-style label ID, e.g. "TEX-12345678-0".
        jurisdiction, inmate_id, index = request_id
        return server.inmate_request_address(jurisdiction, inmate_id, index)

    # Legacy label ID: the bare request autoid.
    return server.request_address(request_id)


def unit_age(
    datetime_fetched: typing.Optional[str], now: datetime.datetime
) -> typing.Optional[datetime.timedelta]:
    """How long ago an inmate's unit was fetched; None if never (or unreadable)."""
    if not datetime_fetched:
        return None

    try:
        fetched = datetime.datetime.fromisoformat(datetime_fetched)
    except ValueError:
        return None

    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=datetime.timezone.utc)

    return now - fetched


def unit_is_stale(
    datetime_fetched: typing.Optional[str], now: datetime.datetime
) -> bool:
    """Whether an inmate's unit was last fetched too long ago (or never)."""
    age = unit_age(datetime_fetched, now)
    return age is None or age > STALE_UNIT_AGE


def stale_unit_warning(
    address: dict[str, typing.Any], now: datetime.datetime
) -> typing.Optional[str]:
    """The out-of-date unit warning for a request address, if one applies."""
    status = address.get("inmate_status")
    if status == INMATE_CURRENT:
        return None

    fetched = address.get("datetime_fetched")
    if not unit_is_stale(fetched, now):
        return None

    if status != INMATE_UNVERIFIED:
        # An older backend that doesn't re-check with TDCJ.
        return (
            "Warning: this inmate's unit has not been checked in over "
            f"{STALE_UNIT_AGE.days} days and may be out of date."
        )

    age = unit_age(fetched, now)
    checked = (
        "has never been checked"
        if age is None
        else f"was last checked {age.days} days ago"
    )
    return (
        "Warning: couldn't re-check this inmate with TDCJ; their unit "
        f"{checked} and may be out of date."
    )


def check_request_address(
    address: dict[str, typing.Any],
    now: typing.Optional[datetime.datetime] = None,
) -> bool:
    """Warn about a request's address; return whether to go ahead and ship.

    An inmate TDCJ no longer lists is never shipped. A possibly out-of-date
    unit only warns. A tossed request needs explicit confirmation, since it
    normally should not be shipped at all. When this returns False it has
    already told the volunteer that nothing was bought.
    """
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)

    questionary.print(
        f"  Shipping to {address['name']} at {address['unit_name']}",
        style="fg:white",
    )

    if address.get("inmate_status") == INMATE_NOT_LISTED:
        logger.warning(
            "TDCJ no longer lists %s (request %s); not shipping",
            address["name"],
            address.get("request_id"),
        )
        questionary.print(
            "  TDCJ no longer lists this inmate (they may have been released). "
            "No postage bought; set this package aside.",
            style="fg:red bold",
        )
        return False

    warning = stale_unit_warning(address, now)
    if warning:
        questionary.print(f"  {warning}", style=WARNING_STYLE)

    if address.get("action") == "Tossed":
        questionary.print(
            "  Warning: this request is marked TOSSED, not filled.",
            style="fg:red bold",
        )
        if console.confirm_tossed():
            return True
        questionary.print("  Skipped; no postage bought.", style=WARNING_STYLE)
        return False

    return True


def generate_addresses_individual(config: Config):
    """Generate addresses for individual shipping."""
    server = Server.from_config(config.ibp)

    while True:
        request_id = console.query_request_id()
        if request_id is None:
            continue

        try:
            with console.task_message("Grabbing address from IBP server"):
                address = fetch_request_address(server, request_id)
        except ServerError as exc:
            questionary.print(f"  {exc.detail}", style="fg:red")
            continue
        except requests.RequestException as exc:
            report_server_unreachable(exc)
            continue

        if not check_request_address(address):
            continue

        to_addr = to_easypost_address(address["name"], address)
        reference = shipping.request_reference(address)

        weight = console.query_weight()
        if weight is None:
            continue

        # Individual packages always go in boxes of one cubic foot or less, so
        # declare the small box without asking; Ground Advantage then competes
        # with Library Mail on actual weight.
        yield to_addr, weight, True, reference


def generate_addresses_manual(config: Config):
    """Generate addresses for manual shipping."""
    gmaps = googlemaps.Client(key=config.googlemaps.apikey)

    while True:
        to_addr = console.query_address(gmaps)
        if not to_addr:
            continue

        weight = console.query_weight()
        if weight is None:
            continue

        small_box = console.query_small_box(weight, shipping.BOX_QUESTION_MIN_LB)
        if small_box is None:
            continue

        yield to_addr, weight, small_box, shipping.MANUAL_REFERENCE


def run_diagnose_printer(_args):
    """Print a snapshot of printer/USB state to help debug detection failures."""
    log_dir = configure_logging(app=DIAG_LOG_APP_NAME, console=False)
    print(
        build_report(discover(), get_backend().recent_print_events(), log_dir=log_dir)
    )


def preview_image(img: Image.Image) -> None:
    """Open an image in the system viewer instead of printing it (dev use)."""
    with build_tempfile(suffix=".png") as tmpfile:
        img.save(tmpfile.name)
        if sys.platform == "win32":
            os.startfile(tmpfile.name)  # pylint: disable=no-member
        else:
            subprocess.check_call(["xdg-open", tmpfile.name])
        # Keep the temp file alive until the viewer has had a chance to open it.
        input("(preview) press Enter to continue ... ")


def shipment_ref(shipment) -> str:
    """What a volunteer searches for in EasyPost: tracking code, else shipment id."""
    return shipment.tracking_code or shipment.id


def warn_if_job_not_ok(shipment, result: PrintResult, log_dir: pathlib.Path) -> None:
    """Tell the volunteer when the spooler could not confirm the label printed."""
    if result.outcome.ok:
        return
    outcome = result.outcome.value
    detail = OUTCOME_DETAILS.get(outcome, f"the printer queue reported '{outcome}'")
    logger.warning(
        "label %s sent to %r but its outcome is %s; it may not have printed",
        shipment_ref(shipment),
        result.printer_name,
        outcome,
    )
    questionary.print(
        f"  Warning: the label was sent to {result.printer_name!r}, but {detail}. "
        "It may not have printed.\n"
        f"  {CREATE_AGAIN_ADVICE}\n"
        f"  Printer logs: {log_dir}",
        style=WARNING_STYLE,
    )


def warn_print_raised(shipment, exc: Exception, log_dir: pathlib.Path) -> None:
    """Tell the volunteer an unexpected print error left the label's fate unknown.

    Anything other than PrintError may have happened after the job reached the
    spooler, so the label is neither refunded nor saved for another try.
    """
    logger.error(
        "unexpected error while printing %s; outcome unknown, not refunded",
        shipment.id,
        exc_info=exc,
    )
    questionary.print(
        f"  Warning: printing failed unexpectedly ({exc}), after the label may "
        "already have reached the printer. It may not have printed.\n"
        f"  {CREATE_AGAIN_ADVICE}\n"
        f"  Printer logs: {log_dir}",
        style=WARNING_STYLE,
    )


@contextlib.contextmanager
def request_refund_on_error(easypost_client, shipment):
    """Manage a shipment context where a refund is requested on error."""
    try:
        yield shipment
    except Exception:
        with console.task_message("Requesting refund"):
            easypost_client.shipment.refund(shipment.id)
        labels.update_status(shipment, labels.STATUS_REFUNDED)
        raise


def check_printer_before_purchase() -> bool:
    """Make sure a label printer is ready (or skipped on purpose) before buying.

    Returns False when the volunteer pressed Ctrl+C, which cancels this
    shipment only, like Ctrl+C at any other prompt.
    """
    try:
        printer_gate.wait_for_printer()
    except KeyboardInterrupt:
        questionary.print(
            "  Cancelled: no postage was bought for this shipment.",
            style=WARNING_STYLE,
        )
        return False
    return True


def report_pending_labels() -> None:
    """One-line notice of labels that are bought but not printed yet."""
    count = len(labels.pending_labels())
    if count:
        questionary.print(f"  {count} label(s) waiting to print", style=WARNING_STYLE)


def prepare_label(shipment, logo: Image.Image | None) -> Image.Image:
    """Download the bought label and stamp the logo on it."""
    with console.task_message("Downloading label"):
        image = grab_png_from_url(shipment.postage_label.label_url)
        if logo is not None:
            image.paste(logo, (450, 425))
    return image


def print_label(shipment, image: Image.Image) -> PrintResult:
    """Print the label on the best usable label printer.

    A failure is reported by the caller (the label is saved for the watcher,
    or may have printed), so nothing is shown here beyond the progress line.

    Raises:
        ibp_printing.PrintError: if the label definitely reached no printer.
    """
    with console.task_message("Printing postage"):
        return print_to_first_available(
            image,
            job_name=f"Shipping Label {shipment.id}",
            track_timeout_s=PRINT_TRACK_TIMEOUT_S,
        )


def save_unprinted_label(
    shipment, image: Image.Image, error: PrintError, meta: dict | None = None
) -> pathlib.Path:
    """Queue a label no printer took for the label watcher.

    Raises:
        Exception: whatever saving raised; the caller then refunds.
    """
    # No console.task_message here: its closing "done!" would run inside the
    # caller's refund context, so a console failure after a successful save
    # would refund a label that is already queued to print.
    try:
        return save_for_retry(image, name=shipment_ref(shipment), meta=meta)
    except Exception as exc:
        questionary.print(
            f"  The label did NOT print ({error}) and could not be saved to print "
            f"later ({exc}). Refunding the postage.",
            style="fg:red",
        )
        raise


def report_saved_label(
    shipment,
    path: pathlib.Path,
    error: PrintError,
    log_dir: pathlib.Path,
    identity: labels.LabelIdentity | None = None,
) -> None:
    """Tell the volunteer the label was saved and will print by itself."""
    logger.warning(
        "label %s did not print (%s); saved to %s", shipment_ref(shipment), error, path
    )
    recipient = identity.recipient_label if identity else "this recipient"
    questionary.print(
        "  The label didn't print. It was saved and will print automatically "
        "when the printer is working.\n"
        f"  Recipient: {recipient}\n"
        f"  Tracking:  {shipment_ref(shipment)}\n"
        f"  Printer logs: {log_dir}",
        style=WARNING_STYLE,
    )


def load_logo() -> Image.Image:
    """Load logo image."""
    logo_fpath = importlib.resources.files("shippy.assets").joinpath("logo.jpg")
    return Image.open(str(logo_fpath))


def load_config(filepath: pathlib.Path) -> Config:
    """Load and validate the config file."""
    parser = configparser.ConfigParser()
    parser.read(filepath)

    config_dict = {
        section: dict(parser.items(section)) for section in parser.sections()
    }
    config = Config.model_validate(config_dict)

    return config


def build_parser() -> argparse.ArgumentParser:
    """Build an arguments parser."""
    parser = argparse.ArgumentParser(description=main.__doc__)

    parser.add_argument("--config", type=pathlib.Path, help="Configuration file path")
    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "open labels in an image viewer instead of printing them (development; "
            "still buys real postage, so use an EasyPost test API key)"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="shipping_type", required=True, help="Select command"
    )

    subparsers.add_parser("individual", help="ship individual packages").set_defaults(
        generate_addresses=generate_addresses_individual
    )

    subparsers.add_parser("bulk", help="ship bulk packages").set_defaults(
        generate_addresses=generate_addresses_bulk
    )

    subparsers.add_parser("manual", help="ship manual packages").set_defaults(
        generate_addresses=generate_addresses_manual
    )

    subparsers.add_parser(
        "diagnose-printer",
        help="print a snapshot of printer/USB state (no config needed)",
    ).set_defaults(func=run_diagnose_printer)

    return parser


def main():
    """Ship to an inmate or a unit."""

    parser = build_parser()
    args = parser.parse_args()

    # Utility subcommands (e.g. diagnose-printer) run without config and exit.
    if getattr(args, "func", None) is not None:
        args.func(args)
        return

    if args.config is None:
        parser.error("--config is required for shipping commands")

    ship(args)


def ship(args: argparse.Namespace) -> None:
    """Run a shipping session until the volunteer closes shippy."""
    config = load_config(args.config)
    log_dir = configure_logging(app=LOG_APP_NAME, console=False)

    easypost_client = easypost.EasyPostClient(config.easypost.apikey)

    logo = load_logo()

    questionary.print(console.WELCOME, style="fg:white")
    questionary.print(
        "\nWelcome! Answer prompts to print postage, hit CTRL+C to cancel and restart\n"
    )

    # Crews often start before Windows has recognised the label printer.
    if not args.preview:
        try:
            printer_gate.wait_for_printer(when="before purchase")
        except KeyboardInterrupt:
            # The volunteer chose to quit ("Press Ctrl+C to quit"). 130 is
            # the usual status for that, so whatever started shippy (the
            # ibp-kiosk launcher) can tell it from a failure.
            sys.exit(130)

    server = Server.from_config(config.ibp)
    from_addr = fetch_until_ok(
        "Grabbing return address from IBP server",
        lambda: shipping.build_address(easypost_client, **server.return_address()),
    )

    try:
        with console.task_message("Verifying return address"):
            easypost_client.address.verify(from_addr.id)
    except easypost.errors.InvalidRequestError:
        questionary.print(
            "  Failed to verify return address, consider double-checking before shipping.",
            style="fg:yellow",
        )

    report_pending_labels()

    for package in args.generate_addresses(config):
        ship_one(
            easypost_client,
            from_addr,
            package,
            config=config,
            args=args,
            logo=logo,
            log_dir=log_dir,
        )
        report_pending_labels()


def fetch_until_ok(message: str, fetch: typing.Callable[[], T]) -> T:
    """Run a startup step that needs the IBP server or EasyPost until it works.

    Nothing can be shipped without it, so a failure doesn't end shippy: as
    with the printer gate, the volunteer fixes the connection and presses
    Enter to try again, or Ctrl+C to quit.
    """
    while True:
        try:
            with console.task_message(message):
                return fetch()
        except (*SERVER_ERRORS, easypost.errors.EasyPostError) as exc:
            logger.error("%s failed", message, exc_info=exc)
            service = (
                "EasyPost"
                if isinstance(exc, easypost.errors.EasyPostError)
                else "the IBP server"
            )
            questionary.print(
                f"  Can't reach {service}. Check the internet connection, then "
                "press Enter to try again (Ctrl+C to quit).",
                style="fg:red",
            )

        try:
            input()
        except KeyboardInterrupt:
            sys.exit(130)


def report_server_unreachable(exc: requests.RequestException) -> None:
    """Tell the volunteer a package's address couldn't be fetched."""
    logger.error("IBP server request failed", exc_info=exc)
    questionary.print(
        f"  Can't reach the IBP server. {NOT_BOUGHT_ADVICE}", style="fg:red"
    )


class PurchaseFailed(Exception):
    """EasyPost failed during the buy itself (``error``), not before it."""

    def __init__(self, error: easypost.errors.EasyPostError):
        super().__init__(str(error))
        self.error = error


def purchase_may_have_completed(exc: Exception) -> bool:
    """Whether a buy that raised ``exc`` may still have bought the label.

    A 4xx answer (other than a timeout) means EasyPost turned the purchase
    down, e.g. for an empty wallet. No answer, a timeout or a 5xx may have
    come after the charge went through.
    """
    status = getattr(exc, "http_status", None)
    refused = isinstance(status, int) and 400 <= status < 500 and status != 408
    return not refused


def report_shipping_error(
    exc: easypost.errors.EasyPostError,
    reference: typing.Optional[str],
    *,
    maybe_bought: bool,
) -> None:
    """Tell the volunteer EasyPost failed for this package, and log it."""
    logger.error(
        "EasyPost failed for %s (%s)",
        reference,
        "purchase may have completed" if maybe_bought else "nothing bought",
        exc_info=exc,
    )
    if isinstance(exc, easypost.errors.FilteringError):
        problem = (
            "No USPS rate was quoted for this package. Check the address and weight."
        )
    else:
        problem = f"EasyPost reported a problem: {exc.message}"
    advice = MAYBE_BOUGHT_ADVICE if maybe_bought else NOT_BOUGHT_ADVICE
    questionary.print(f"  {problem}\n  {advice}", style="fg:red")


def ship_one(  # pylint: disable=too-many-arguments,too-many-locals
    easypost_client,
    from_addr,
    package: tuple,
    *,
    config: Config,
    args: argparse.Namespace,
    logo: Image.Image | None,
    log_dir: pathlib.Path,
) -> None:
    """Buy and print postage for one package from ``args.generate_addresses``.

    An EasyPost failure is shown and logged, and the volunteer goes on to the
    next package. Nothing is refunded or checked here for a buy that may have
    gone through: an unused label is refunded by the weekly job.
    """
    to_addr_dict, weight, small_box, reference = package
    identity = labels.identity_for(to_addr_dict)

    try:
        to_addr = shipping.build_address(easypost_client, **to_addr_dict)
        verify_address(
            easypost_client, to_addr, typed=args.shipping_type in TYPED_ADDRESS_MODES
        )

        if not args.preview and not check_printer_before_purchase():
            return

        shipment = purchase_postage(
            easypost_client,
            from_addr,
            to_addr,
            16.0 * weight,  # Convert to ounces.
            config.parcel.dimensions(small_box),
            reference=reference,
        )
    except PurchaseFailed as failed:
        report_shipping_error(
            failed.error,
            reference,
            maybe_bought=purchase_may_have_completed(failed.error),
        )
        return
    except easypost.errors.EasyPostError as exc:
        report_shipping_error(exc, reference, maybe_bought=False)
        return

    record = labels.record_purchase(identity, shipment)

    ship_label(
        easypost_client,
        shipment,
        logo,
        args.preview,
        log_dir,
        journal=(identity, record),
    )


def verify_address(easypost_client, to_addr, *, typed: bool) -> None:
    """Check a recipient address with EasyPost; a failure never blocks shipping.

    Only a typed address (``typed``, manual mode) is something the volunteer
    can double-check, so only then is the check shown. Addresses from the IBP
    server (individual and bulk) are checked quietly and a failure is logged.
    """
    progress = (
        console.task_message("Verifying address") if typed else contextlib.nullcontext()
    )
    try:
        with progress:
            easypost_client.address.verify(to_addr.id)
    except easypost.errors.InvalidRequestError as exc:
        logger.warning(
            "could not verify %s address %s: %s",
            "typed" if typed else "IBP server",
            to_addr.id,
            exc,
        )
        if typed:
            questionary.print(
                "  Failed to verify address, consider double-checking before "
                "shipping.",
                style=WARNING_STYLE,
            )


def purchase_postage(  # pylint: disable=too-many-arguments
    easypost_client,
    from_addr,
    to_addr,
    weight: float,
    dimensions,
    *,
    reference: typing.Optional[str] = None,
):
    """Quote the package, show the rates being compared, then buy the cheapest.

    ``reference`` tags the shipment with what it was bought for.

    Raises:
        PurchaseFailed: EasyPost failed during the buy itself.
        easypost.errors.EasyPostError: it failed before the buy.
    """
    with console.task_message("Getting rates"):
        quote = shipping.quote_shipment(
            easypost_client,
            from_addr,
            to_addr,
            weight,
            dimensions,
            reference=reference,
        )
    rate = shipping.cheapest_rate(quote)
    show_rate_summary(shipping.summarize_rates(quote.rates, rate))
    with console.task_message("Purchasing postage"):
        try:
            return shipping.buy_shipment(easypost_client, quote, rate)
        except easypost.errors.EasyPostError as exc:
            raise PurchaseFailed(exc) from exc


def show_rate_summary(summary: shipping.RateSummary) -> None:
    """Print the price comparison (and any warning) before buying."""
    questionary.print(f"  {summary.line}", style="fg:white")
    if summary.warning:
        questionary.print(f"  Warning: {summary.warning}", style=WARNING_STYLE)
    logger.info("rates: %s", summary.line)


def ship_label(  # pylint: disable=too-many-arguments
    easypost_client,
    shipment,
    logo: Image.Image | None,
    preview: bool,
    log_dir: pathlib.Path,
    *,
    journal: tuple[labels.LabelIdentity | None, object] = (None, None),
) -> None:
    """Turn a bought shipment into a printed (or saved) label.

    Refunds happen only where no label can have reached a printer: while
    preparing the image, and when a label that definitely did not print could
    not be saved for the label watcher. Everything after a print call was
    made (other than a definite PrintError) or after the label was saved sits
    outside any refund context.

    ``journal`` is the label's (identity, record) in the shared label journal;
    its status is updated with the print outcome.
    """
    identity, record = journal
    # No label image yet (download/logo failed): nothing can print, refund.
    with request_refund_on_error(easypost_client, shipment):
        image = prepare_label(shipment, logo)
        if preview:
            preview_image(image)
            return

    try:
        result = print_label(shipment, image)
    except PrintError as error:
        # The label definitely reached no printer. Keep the postage and queue
        # the label for the label watcher; refund only if the label cannot even
        # be saved (save_unprinted_label re-raises).
        meta = labels.retry_meta(identity, shipment, record)
        with request_refund_on_error(easypost_client, shipment):
            path = save_unprinted_label(shipment, image, error, meta)
        labels.update_status(shipment, labels.STATUS_QUEUED, file=path)
        report_saved_label(shipment, path, error, log_dir, identity)
        return
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Not a PrintError: we can't tell whether the job reached the spooler,
        # so treat it as uncertain (no refund, no automatic retry).
        labels.update_status(shipment, labels.STATUS_CHECK_PRINTER)
        warn_print_raised(shipment, exc, log_dir)
        return

    # The job was spooled, so the label may well have printed. Refunding here
    # could leave a printed label with no postage.
    labels.update_status(
        shipment,
        labels.STATUS_PRINTED if result.outcome.ok else labels.STATUS_CHECK_PRINTER,
    )
    warn_if_job_not_ok(shipment, result, log_dir)

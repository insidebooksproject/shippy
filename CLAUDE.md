# shippy and shippy-gui — Claude Code Instructions

## Project Overview

One package, `shippy`, holds the two apps the Inside Books Project (IBP)
shipping stations use to print shipping labels for books sent to people
incarcerated in Texas:

- **`shippy`** (`shippy.cli`): the command-line app for scanned requests
  (`individual`) and unit mailrooms (`bulk`), plus `manual`. Entry point
  `shippy = "shippy.cli:main"`; config passed with `--config` (the laptops use
  `C:\Users\insid\config.ini`).
- **`shippy-gui`** (`shippy.gui`): the PySide6 desktop app for typed
  addresses ("Ship Manual"). Gui-script `shippy-gui = "shippy.gui.__main__:main"`;
  reads and writes `config.ini` in its working directory.
- **`shippy.core`**: everything the two share. It must never import Qt or
  prompt-toolkit/questionary (`tests/core/test_imports.py` checks).

Both buy EasyPost postage, take the return address from the IBP server, and
print through the shared `ibp-printing` library. Until 2026-11 shippy-gui was
its own repo (`insidebooksproject/shippy-gui`); its history is merged in here.

**Python version:** 3.12 (see `.python-version`)
**Build backend:** `uv_build`; **dependency/environment manager:** `uv` (lockfile: `uv.lock`)
**Extras:** `gui` adds PySide6. A plain `shippy` install (the CLI) must not pull
in or import PySide6; the stations run
`uvx --from "shippy[gui] @ git+https://github.com/insidebooksproject/shippy.git@deploy" shippy-gui`.

## Project Structure

```
src/shippy/
  __main__.py            # python -m shippy -> the CLI
  core/                  # shared, Qt-free and prompt-toolkit-free
    addresses.py         # Google Maps geocoding + address component parsing
    ibp_server.py        # IBP server client (Server, ServerError, JURISDICTIONS)
    label_image.py       # label PNG download, the IBP logo and where it goes
    label_journal.py     # ibp-printing label journal glue (identity/key, statuses)
    log.py               # app names (journal app=, printer-<app> logs), printer log setup
    models.py            # config models: [ibp], [easypost], [googlemaps], [parcel]
    postage.py           # EasyPost address fields, shipment quote/buy, references
    purchase.py          # buy-failure outcomes, refusal rules, shared volunteer advice
    rates.py             # USPS service names and quoted prices
    assets/logo.jpg
  cli/
    app.py               # argparse, the shipping loop, buy/print/save/refund flow
    console.py           # questionary prompts
    printer_gate.py      # NO LABEL PRINTER FOUND wait before buying
    rates.py             # the rate line shown before buying
    autocompletion.py    # prompt-toolkit Google Maps completer (+ `autocomplete` demo)
    addresses.py         # `addresses` demo script
  gui/
    __main__.py          # App entry point; config bootstrap and startup
    main_window.py       # Top-level QMainWindow
    shipping_tab.py      # Main shipping form tab
    settings_dialog.py   # Settings/config dialog
    shipping_coordinators.py # Create Label flow: printer gate, box answer, result dialogs
    config.example.ini   # Bundled template written to a missing config.ini
    core/                # shippy-gui's own non-Qt logic
      config.py          # INI loading via configparser
      config_manager.py  # ConfigManager class (load/save/validate)
      models.py          # GUI config ([ui], non-blank keys) and address models
      constants.py       # App-wide constants
      services.py        # EasyPost wrapper (ShipmentService; PurchaseError)
      rates.py           # Quoted-rates summary shown after buying
      ibp_server.py      # Return address, sorted into unreachable / bad address
      logging.py         # shippy-gui's own rotating log file
      font.py            # Font size application
      shipment_workflow.py # Buy/print/save/refund orchestration
    widgets/             # address_form, shipment_controls, autocomplete,
                         # label_queue ("Label Will Print Later", "Waiting to print"),
                         # printer_gate (NoPrinterDialog)
    workers/shipment_worker.py # QThread worker for async shipment creation
    printing/            # thin adapters over ibp_printing + Qt print dialog
tests/
  conftest.py            # canned IBP server responses, FakeHttp `http` fixture
  core/  cli/  gui/      # one folder per package; gui/ runs Qt offscreen
config.example.ini       # template for both apps (the CLI ignores [ui])
```

Scripts: `shippy`, `shippy-gui`, `diagnose-printers`
(`ibp_printing.diagnostics:main`, the same tool as ibp-printing's
`ibp-print-diag`), and the `autocomplete`/`addresses` demos.

## Environment Setup

```bash
uv venv
source .venv/bin/activate
uv sync --all-extras
uv run pre-commit install
```

`uv sync` also installs the `dev` group (black, mypy, pylint, pytest, and
PySide6 for the GUI tests). `ibp-printing` is pinned to a git tag of
https://github.com/insidebooksproject/printing in `[tool.uv.sources]`; to
develop both together, temporarily point it at a checkout in `../printing`
(`{ path = "../printing", editable = true }`).

## Running the Apps

```bash
shippy --config config.ini individual   # or python -m shippy ...
shippy-gui                              # or python -m shippy.gui, from the folder with config.ini
```

`shippy --preview` opens labels in an image viewer instead of printing but
still buys real postage; use an EasyPost test key.

## Configuration

- Never commit `config.ini` (gitignored) or real keys.
- Both apps read the same sections through `shippy.core.models`; shippy-gui's
  `Config` (`gui/core/models.py`) adds `[ui]` and refuses blank API keys. The
  laptops' existing `config.ini` files must keep working: never rename a
  section or key, and keep new keys optional.
- shippy-gui: always use `ConfigManager` or `load_config()` — never read
  `config.ini` directly. On first launch it creates `config.ini` from the
  bundled `gui/config.example.ini` and opens Settings.
- If you change setup, config fields, startup, platform behaviour or the
  volunteer-visible workflow, update `README.md` (and, for config fields,
  `config.example.ini` and `gui/config.example.ini`) in the same unit of work.

## Code Quality

Pre-commit hooks and CI (Ubuntu and Windows) run:
- `uv run black --check src tests` (format with `uv run black src tests`)
- `uv run pylint src` (must stay at 10.00; its duplicate-code check catches
  logic copied between the apps: move it to `shippy.core` instead)
- `uv run mypy src`
- `uv run pytest` (the GUI tests set `QT_QPA_PLATFORM=offscreen` themselves;
  CI on Linux also needs `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`)

Avoid POSIX-only code: CI and the shipping laptops run Windows. Run the checks
that match what you touched; add an app launch smoke check when changing UI
or startup code. If you cannot run a meaningful check, say so.

## Git Workflow

- All work is done on **feature branches** branched from `main`.
- Commits must be **atomic and focused** — each commit should represent the smallest coherent unit of change; do not mix unrelated changes.
- Use **single-line commit messages** with an appropriate conventional tag:
  - `feat:` — new feature
  - `bugfix:` — bug fix
  - `refactor:` — code restructuring without behavior change
  - `chore:` — build, deps, tooling, config
  - `docs:` — documentation only
  - `test:` — tests only
- Do **not** include "Co-Authored-By" or any AI attribution in commit messages.
- Merge feature branches straight into `main` with `git merge --no-ff`; no
  pull requests and no review (one maintainer).
- `main` and `deploy` are kept identical, and every station runs `deploy`:
  release by fast-forwarding it (`git push origin main:deploy`) after the
  change is tested; never commit to `deploy` directly or let it diverge from
  `main`. Details and rollback: [README.md](README.md#releasing).

## Contracts That Must Not Change

- App names (`shippy.core.log`): `CLI_APP = "shippy"`, `GUI_APP = "shippy-gui"`,
  `DIAG_APP = "diag"`. They name the printer logs (`printer-<app>.log`/`.jsonl`
  in `%LOCALAPPDATA%\ibp-printing\logs`, `~/.local/state/ibp-printing/logs` on
  Linux) and tag each label in the shared journal (`app=`).
- The journal key: `label_journal.identity_for` builds `recipient_key` from
  the recipient address (street1 + street2 joined by a space) for both apps,
  so they and the label watcher see each other's labels.
- EasyPost `reference`: `ibp1:req:<code>`, `ibp1:unit:<jurisdiction>:<name>`,
  or `ibp1:manual` (every shippy-gui label); see `core/postage.py`.
- CLI flags and subcommands (`--config`, `--preview`, `individual`, `bulk`,
  `manual`, `diagnose-printer`), exit status 130 for Ctrl+C at startup, 1
  after an unexpected error; shippy-gui's `config.ini` in its working
  directory and its log file (`ui.log_file`, default `shippy.log`).

## Key Patterns

- Share, don't copy: logic both apps need goes in `shippy.core`. Keep
  app-specific flow (questionary prompts, Qt widgets and workers, each app's
  own wording around the shared messages) in its app. Never hardcode secrets,
  API keys, printer names or machine-specific paths.
- Printing (discovery, platform backends, USB VID:PID matching, job tracking, printer logs) lives in the shared `ibp-printing` library (`ibp_printing`). The CLI calls it directly; `gui/printing/printer_manager.py` is only a thin adapter. Fix printer behaviour in ibp-printing, not here, and do not add platform checks to the apps.
- Logging: shared code logs with `shippy.core.log.get_logger(__name__)`, under
  ibp-printing's logger, so its records reach the running app's printer logs
  (the CLI has no other log file); shippy-gui also adds its own rotating log
  file (`gui/core/logging.py`), which gets INFO+ records including printer ones.
- shippy-gui: preserve the PySide6 signal/slot patterns; network operations
  (EasyPost, Google Maps) run in `QThread` workers to keep the UI non-blocking.
- Tests fake printers with `ibp_printing.set_backend(FakeBackend())` (see `tests/gui/test_printer_manager.py`); reset with `set_backend(None)`. Tests never touch the real journal: use `tests/gui/journal_fakes.install_fake_journal(self)`, mock `shippy.core.label_journal.ibp_printing`, or `ibp_printing.labels.set_journal_path(tmp)` when calling the real `save_for_retry`.

### Refund rules after postage is bought (both apps)

Preserve them when touching `cli/app.py` (`ship_label`) or
`gui/workers/shipment_worker.py` / `gui/core/shipment_workflow.py` (covered by
`tests/cli/test_main_loop.py`, `tests/cli/test_print_messages.py` and
`tests/gui/test_shipment_workflow.py`):

- **No label image yet** (label download, decoding, or logo fails): refund.
- **`ibp_printing.PrintError`** (the job definitely reached no printer): do NOT refund. Save the rendered label (with logo) with `ibp_printing.save_for_retry(image, name=tracking_code, meta=...)` into `<Downloads>/to-print/`, where the IBP label watcher prints it once a printer works. The CLI prints "The label didn't print. It was saved and will print automatically when the printer is working." with the recipient and tracking; shippy-gui tells the volunteer via `ShipmentWorker.label_saved` (status line + calm "Label Will Print Later" information box from `widgets/label_queue.py`; the form is cleared like a success). Only if saving fails is the shipment refunded.
- **Spooled but not `.ok`** (incl. `JobOutcome.UNCERTAIN` / `TRACKING_FAILED`): do NOT refund (the label may still print) and do NOT queue it; warn (shippy-gui: `ShipmentWorker.success_with_warning`, "Check The Printer") that it may not have printed, with `purchase.CHECK_PRINTER_ADVICE` (create it again if no label came out, since the unused one is refunded automatically).
- **Any other exception from the print call** (not a `PrintError`): treated as uncertain, because the job may have reached the spooler — warn, do NOT refund, do NOT save. Refund contexts cover only label preparation and the save-for-retry-failed fallback; building/showing messages after a spool or save must never refund.
- **shippy-gui Shift+Click Qt dialog path** (`print_image_with_dialog` → `DialogPrintStatus`, handled in `shipping_coordinators.py`): `CANCELED` → refund; `NOT_SENT` (failed before `QPainter.begin()` succeeded) → `ShipmentWorkflow.save_unprinted_label` + "Label Will Print Later" box (refund only if saving fails); `UNCERTAIN` (failed after `begin()`) → "Check The Printer" warning, no refund.

### Buy errors and volunteer messages

`shippy.core.purchase` sorts a failed purchase into three outcomes
(`classify_buy_failure`) and words the advice for each
(`buy_failure_advice(..., item="package")` in the CLI, `item="shipment"` in
shippy-gui, which prefixes "The label could not be created."):

- Before the buy request (addresses, quote, no rate), or a buy EasyPost turned
  down with a 4xx other than 408 → "No postage was bought", except a
  `PaymentError`/402 → "The EasyPost account can't pay for postage right now.
  Tell a coordinator".
- A buy request that may still have gone through (no answer, timeout, 408,
  5xx; in shippy-gui any non-EasyPost exception too:
  `purchase_may_have_completed`, so `ShipmentService.buy_shipment` raises
  `PurchaseError`) → "The purchase may not have completed. Try this ... again;
  an unused label is refunded automatically", with no refund attempt.
- Messages name the stage, not the raw error (details go to the log with
  `exc_info`). shippy-gui's return address problems →
  `SERVER_UNREACHABLE_MESSAGE` (`IbpServerUnreachable`) or
  `SERVER_BAD_ADDRESS_MESSAGE` in `shipment_worker.py`; the CLI waits at
  startup (`fetch_until_ok`) and asks for a coordinator when a request was
  refused (`purchase.is_refusal`).
- Volunteer prompts stay minimal: unused labels (never scanned by USPS) are refunded automatically every week by `ibp-label-refund.timer` on the IBP server, so an occasional duplicate or unprinted label is an accepted risk. Do not add a duplicate-label question, purchase-path reconciliation, or "do NOT create it again" / "delete it from to-print" / "refund in EasyPost" instructions to volunteer-facing texts.

### Printer check before buying

- CLI: `cli/printer_gate.wait_for_printer` at startup and before each purchase
  (`NO LABEL PRINTER FOUND`; Enter continues without a printer, Ctrl+C quits
  at startup / cancels the shipment before a purchase).
- shippy-gui: `ShipmentControls.start_printer_polling()` (started by `ShippingTab`) re-scans `get_available_printers()` on a background thread every `PRINTER_POLL_MS`, paused while the controls are disabled (a label in progress), and drives the printer status line. Before buying (not on Shift+Click), `ShipmentFlowCoordinator` calls `widgets/printer_gate.wait_for_printer`: with no printer it shows `NoPrinterDialog`, which closes itself once a scan finds one; "Continue anyway" buys with an empty printer name, and `print_prepared_label` then saves the label for the watcher (as a `PrintError`) without trying to print.

### Shared label journal

ibp-printing's journal, also written by the label watcher, wrapped by
`shippy.core.label_journal` (each call passes `app=CLI_APP` or `GUI_APP`):

- There is no duplicate check before buying: shipping several boxes to one address is normal work.
- **After buying**, each app calls `record_purchase`; the print outcome then sets `printed`, `check_printer` (spooled but not ok, uncertain/unexpected errors, dialog `UNCERTAIN`), `queued` (with the saved file) or `refunded` (only when the app's refund succeeded). Journal calls never raise (except `pending_labels`, whose callers handle it) and must never change the refund rules above.
- The CLI prints `N label(s) waiting to print` at startup and after each shipment; shippy-gui's `widgets/label_queue.py` `PendingLabelsIndicator` shows "Waiting to print: N" in the status bar (hidden at 0), reading `pending_labels()` on a background thread every 10 s and after each shipment.

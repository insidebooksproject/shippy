# shippy

The Inside Books Project (IBP) shipping stations print shipping labels for
books sent to people incarcerated in Texas with two apps from this one
package:

- **`shippy`**, the command-line app, for packages to a scanned request
  (`individual`) or to a unit's mailroom (`bulk`). It gets the recipient and
  return addresses from the IBP server.
- **`shippy-gui`**, the PySide6 desktop app ("Ship Manual"), for packages to
  an address typed in, with Google Maps autocomplete. It takes the return
  address from the IBP server too.

Both buy the cheapest USPS postage through the EasyPost API and print the
label, with the IBP logo, on a USB label printer through the shared
[`ibp-printing`](https://github.com/insidebooksproject/printing) library. A
label that cannot reach any printer is saved to a print queue folder instead
of being thrown away (see [When a label does not print](#when-a-label-does-not-print)).
What the two apps have in common (config, the IBP server client, EasyPost
purchases, rates, the label journal, error messages) is one shared copy in
`shippy.core`, so a fix there reaches both.

## About Inside Books Project

Inside Books Project is an Austin-based community service volunteer organization that sends free reading materials to people incarcerated in Texas, and also publishes resource guides and short-form instructional pamphlets. Inside Books is the only books-to-prisoners program in Texas, where more than 120,000 people are behind bars. Inside Books Project works to promote reading, literacy, and education among incarcerated individuals and to educate the general public on issues of incarceration.

## Configuration

Both apps read the same `config.ini` format (see `config.example.ini` for a
full example): the IBP server, EasyPost and Google Maps, plus an optional
`[parcel]` section and, for shippy-gui, `[ui]`. The CLI ignores `[ui]`.

```ini
[ui]
font_size = 11
log_file = shippy.log
default_weight = 3

[ibp]
url = http://192.168.1.156/api

[easypost]
apikey = your_easypost_api_key_here

[googlemaps]
apikey = your_googlemaps_api_key_here
```

- `ibp.url`: The base URL of the IBP backend API. The nginx-prefixed form
  (`http://host/api`) and the direct form (`http://host:8000`) both work. No
  IBP API key is needed; an `apikey` line (shippy-gui's Settings still has
  the field) is stored but never sent.
- `easypost.apikey`: Your EasyPost API key.
- `googlemaps.apikey`: Your Google Maps API key (address autocompletion in
  shippy-gui and in the CLI's `manual` mode). The section is required by
  both apps. shippy-gui refuses a blank key for either service.
- `[parcel]` (optional): the declared box in inches. `length`, `width` and
  `height` (default 20 x 14 x 10) are the box used unless the volunteer says
  the box is small; `small_length`, `small_width` and `small_height`
  (default 12 x 12 x 12) are the small box, which must be whole inches,
  exactly one cubic foot, with no side over 22.
- `[ui]` (shippy-gui only): `font_size` (UI font size in points, 8-24),
  `log_file` (shippy-gui's log file, relative to the config's folder or
  absolute; default `shippy.log`), `default_weight` (pounds).

The return address and the recipient name for unit (bulk) shipments
(`ATTN: MAILROOM STAFF`) are not set in `config.ini`: both apps read them from
the server's `/shipping-settings`, which volunteers can edit in the IBP web
app. shippy-gui reads the return address each time a label is bought; if the
server can't be reached, no postage is bought.

Where each app finds its config:

- `shippy` is given it with `--config`, required for every shipping mode.
- `shippy-gui` reads `config.ini` from the folder it is started in. If it is
  missing, the app creates one from its packaged `config.example.ini`, shows
  a configuration error and opens Settings so you can fill in the required
  values; if it is incomplete or invalid, it shows the error and opens
  Settings too. If you cancel Settings, or the values are still invalid, the
  app exits. Settings are always saved to `config.ini`.

## Running the apps

The stations run the `deploy` branch straight from GitHub with
[uv](https://github.com/astral-sh/uv)'s `uvx` (see [Releasing](#releasing)).
A plain install has only the CLI's dependencies; shippy-gui needs the `gui`
extra, which adds PySide6:

```
uvx --from git+https://github.com/insidebooksproject/shippy.git@deploy shippy --config path/to/your/config.ini <shipping_type>
uvx --from "shippy[gui] @ git+https://github.com/insidebooksproject/shippy.git@deploy" shippy-gui
```

**Example:**

```
uvx --from git+https://github.com/insidebooksproject/shippy.git@deploy shippy --config config.ini bulk
```

The shipping laptops' SHIP BULK and SHIP INDIVIDUAL shortcuts run `shippy`
with `--config C:\Users\insid\config.ini` and `bulk` or `individual`, and SHIP
MANUAL runs `shippy-gui` from the folder with its `config.ini`.

To wrap a command in PowerShell, for a desktop shortcut:

```
powershell.exe -NoExit -Command "& { & 'uvx' --from 'git+https://github.com/insidebooksproject/shippy.git@deploy' 'shippy' --config 'C:\path\to\your\config.ini' 'bulk' }"
powershell.exe -NoExit -Command "& { & 'uvx' --from 'shippy[gui] @ git+https://github.com/insidebooksproject/shippy.git@deploy' 'shippy-gui' }"
```

To create a shortcut: right-click the desktop, **New → Shortcut**, paste the
command as the location, name it and click **Finish**. For shippy-gui, set
**Start in** in the shortcut's **Properties** to the folder with
`config.ini`. Or point the shortcut at a small `.cmd` launcher, which sets
the folder itself:

```bat
@echo off
setlocal

REM Set working directory (where shippy-gui's config.ini lives)
cd /d "C:\InsideBooks\ShippyGUI"

REM Run the app
uvx --from "shippy[gui] @ git+https://github.com/insidebooksproject/shippy.git@deploy" shippy-gui
```

From a local checkout (see [Development](#development)), run `shippy` (or
`python -m shippy`) with the same arguments, and `shippy-gui` (or
`python -m shippy.gui`) from the folder with `config.ini`:

```
shippy --config config.ini individual
```

## The shippy CLI

### Shipping modes

Replace `<shipping_type>` with one of the following commands:

- `individual`: For shipping individual packages. Scan the request label
  (new `TEX-12345678-0` style or a legacy number). The IBP server re-checks
  the inmate with TDCJ and says how that went (`inmate_status` on the
  address):
  - `current`: shippy ships normally.
  - `not_listed` (TDCJ no longer lists the inmate, e.g. released): shippy
    buys nothing and asks nothing; it says to set the package aside.
  - `unverified` (TDCJ couldn't be reached), or a server too old to send the
    field: shippy warns if the inmate's unit was last checked over 90 days
    ago and may be out of date, but still ships.

  shippy asks for confirmation (default No) before buying postage for a
  request marked tossed. It doesn't ask about box size: every individual
  package is declared as the small box (12x12x12, one cubic foot), so pack
  individual requests in boxes no bigger than that.
- `bulk`: For shipping a box to a unit's mailroom. Pick the unit from the
  server's list.
- `manual`: For typing the address, with Google Maps autocompletion (the
  stations use shippy-gui for this). If Google Maps can't find the address,
  shippy asks for it again.

In `bulk` and `manual`, packages of 4 pounds or more get one question
(default No): is the box 1,728 cubic inches or less, each side rounded up to
a whole inch, with no side over 22 inches? Yes declares the small box, so
Ground Advantage can compete with Library Mail on actual weight. Below 4
pounds Library Mail is always cheaper, so nothing is asked. Before buying, shippy
shows the rates it compared and buys the cheapest USPS rate.

Every recipient address is checked with EasyPost before buying, and a
failed check never stops shipping. Only in `manual` mode, where the
volunteer typed the address, does shippy show "Failed to verify address,
consider double-checking before shipping."; `individual` and `bulk`
addresses come from the IBP server, so a failed check there is only logged.

Each EasyPost shipment's `reference` records what the label was bought for,
so the IBP server can match labels to requests: `ibp1:req:<request code>`
(`individual`, with the code the server returned, e.g.
`ibp1:req:TEX-00012345-2`), `ibp1:unit:<jurisdiction>:<unit name>` (`bulk`,
e.g. `ibp1:unit:Texas:BETO`), or `ibp1:manual` (`manual` and every
shippy-gui label, an older server that sends no request code, or anything
unexpected). It is built from data already in hand and never stops a
purchase.

### No label printer

At startup, and again before each purchase, shippy checks for a usable label
printer. If there is none it shows `NO LABEL PRINTER FOUND` and carries on by
itself as soon as a printer is ready. Pressing Enter continues without a
printer (labels are then saved for the label watcher, below). Ctrl+C at
startup quits shippy with exit status 130, so a launcher such as the kiosk's
can tell it from a failure; before a purchase it cancels only that shipment,
and no postage is bought. `--preview` skips this check.

### When EasyPost or the IBP server fails

A failure for one package (the IBP server can't be reached, or EasyPost
fails or quotes no USPS rate) skips only that package: shippy says what went
wrong, logs it, and asks for the next one. Before the purchase it says "No
postage was bought. Try this package again." If the purchase itself failed
without a clear answer from EasyPost (a timeout, a lost connection, a server
error), the charge may have gone through, so it says "The purchase may not
have completed. Try this package again; an unused label is refunded
automatically." shippy doesn't check for or refund such a label itself. If
EasyPost refuses the payment, it says "The EasyPost account can't pay for
postage right now. Tell a coordinator; no postage was bought." (shippy-gui
says the same, about "this shipment".)

If the return address (or, for bulk, the units list) can't be fetched or
checked at startup, shippy waits: press Enter to try again, or Ctrl+C to
quit (exit status 130). It says it can't reach the IBP server or EasyPost,
or, when one of them turned the request down (e.g. EasyPost rejected the
return address), gives the reason and asks for a coordinator. Any other
error it didn't expect is logged (also to `errors-shippy.jsonl`, see
[Logs](#logs)), and shippy says "shippy hit a problem it
didn't expect. The details are in <log folder>. Press Enter to close." before
exiting with status 1.

## shippy-gui

### Settings

Go to **File → Settings** (or press `Ctrl+,`), fill in the IBP server URL and
the API keys, and click **Save**. The dialog validates the configuration and
saves it to `config.ini`. Other keyboard shortcuts: `Ctrl+Q` quits.

### Creating a label

1. **Enter the recipient address**: type it in the search field and pick a
   Google Maps autocomplete suggestion; the address fields fill in by
   themselves and stay editable.
2. **Enter the package weight** in pounds (1-70). At 4 pounds and up, tick
   the box-size checkbox only if the box is 1,728 cubic inches or less (each
   side rounded up to a whole inch) with no side over 22 inches; its tooltip
   has examples. Leave it unticked if unsure. Changing the address clears it.
3. **Select the printer** from the dropdown (it updates by itself a few
   seconds after a printer is plugged in; **Refresh** scans right away).
4. **Click "Create Label"**:
   - If no label printer is found, a "No label printer detected" window waits
     for one and closes by itself when it appears. **Continue anyway** buys
     the label and saves it to `Downloads\to-print\` for the label watcher;
     **Cancel** buys nothing.
   - shippy-gui buys the cheapest USPS rate via EasyPost (Library Mail, or
     Ground Advantage when the small box makes it cheaper), tagged
     `ibp1:manual`, and shows the rates it compared.
   - It downloads the label, stamps the IBP logo on it, prints it and shows
     the tracking number.
   - If no printer can take the label, it saves it to `Downloads\to-print\`
     to print later (postage is **not** refunded; see
     [When a label does not print](#when-a-label-does-not-print)); it refunds
     right away only if the label cannot be downloaded or prepared.

Shift + Click on "Create Label" uses the Qt system print dialog instead.
Canceling that dialog refunds the postage. If printing cannot even start, the
label is saved to `Downloads\to-print\` like any other label no printer took;
if it fails after printing started, you get the "Check The Printer" warning and
nothing is refunded right away.

The status bar shows **Waiting to print: N** while labels are queued in
`to-print\` or waiting at the printer (it is hidden when there are none, and
refreshes every 10 seconds and after each shipment). Click it to see who each
label is for, its tracking number, its status and when it was queued.

### Troubleshooting shippy-gui

- **"Configuration Error" on startup**: make sure `config.ini` exists and is
  properly formatted; use File → Settings to validate and save it.
- **"Failed to verify recipient address"**: non-blocking; the label is still
  bought. Double-check the address before shipping. "Failed to verify return
  address" means the return address in the IBP server's shipping settings
  (editable in the IBP web app) needs checking.
- **"Shipment Error"**: the box says in plain words whether postage was
  bought; the technical details (the EasyPost or IBP server error) go to the
  shippy-gui log file (`ui.log_file`). The form is kept, so trying again is
  one click.
  - "No postage was bought": creating the label failed before buying (the
    addresses, the quote or no usable rate), or EasyPost turned the purchase
    down. Try the shipment again.
  - "The EasyPost account can't pay for postage right now": EasyPost refused
    the purchase for lack of funds; nothing was bought. Tell a coordinator,
    who can top up the EasyPost wallet.
  - "The purchase may not have completed": the buy request got no answer,
    timed out or hit an EasyPost server error, so the charge may have gone
    through. Try the shipment again; if the first label was bought, it is
    never used and the weekly refund job refunds it.
  - "The IBP server can't be reached": the return address could not be read,
    so nothing was bought. Check that the laptop is online and try again.
  - "The IBP server didn't send a usable return address": the return address
    in the IBP server's shipping settings (IBP web app) needs fixing.
- **Google Maps autocomplete not working**: check the Google Maps API key in
  Settings, that the Places API is enabled in the Google Cloud Console, and
  that there is API quota left.

## Label printers

Printing is handled by `ibp-printing`, and only USB label printers are used.
Postage never goes to a printer ibp-printing knows is for package labels (an
SP310 or a DYMO LabelWriter 450): neither app lists or counts one, so with
only such a printer plugged in, both show their no-printer prompt before
buying.
A supported printer (the PM2411BT the shipping laptops use) is printed to
directly over USB, with no print queue or naming rule, and is tried first
(shippy-gui lists it first, e.g. `PM2411BT (USB direct, serial ...)`). On
Linux that is the only way to print: there are no print queues (ibp-printing
dropped CUPS on 2026-11-26). On Windows, any other printer is used through a
local print queue only when **both** of these hold:

1. The queue name ends in the printer's USB `VID:PID`, separated from the rest of
   the name by a space, tab, `_` or `-` — e.g. `DYMO LabelWriter 450 0922:0028`.
   Only local print queues are considered (USB label printers are local;
   network printer connections are skipped so a dead print server cannot
   stall printing).
2. A USB device with that `VID:PID` is currently plugged in.

If several printers qualify, healthy, problem-free and default queues are tried
first (shippy-gui still lists printers that report a problem, lower down); if
one fails before the job is spooled, shippy tries the next one. After
spooling, shippy follows the job for up to 30 seconds and shippy-gui for up
to 15.

### When a label does not print

Unused labels are refunded automatically: a weekly job on the IBP server
refunds every label USPS never scanned (EasyPost allows this within 30 days
of purchase). So neither app stops volunteers over an occasional extra
label, and neither sends them to EasyPost to refund one.

What both apps do once postage has been bought:

- **The label could not be downloaded or prepared** (no label image exists):
  the postage is refunded right away.
- **No printer could take the label** (no label printer plugged in, or every
  printer failed before the job was sent): the label, with the IBP logo, is
  saved to the print queue folder `Downloads\to-print\`, and the IBP label
  watcher (from ibp-printing) prints it as soon as a label printer is working.
  shippy says:

  ```
  The label didn't print. It was saved and will print automatically when the printer is working.
  Recipient: Jane Doe #00012345, Rt 2 Box 4400, Gatesville, TX
  Tracking:  9400...
  Printer logs: ...
  ```

  and carries on with the next package; shippy-gui shows the same in a
  "Label Will Print Later" box and clears the form. Only if the label cannot
  even be saved is the postage refunded right away (the app says so).
- **The label was sent to a printer but the queue reported a problem**, or it
  could not be confirmed that the job reached the printer, or printing failed
  with an unexpected error: the label may well still print, so it is neither
  refunded nor queued again. The app warns that it may not have printed
  (shippy-gui: "Check The Printer") and says: "Check the printer. If no label
  came out, create it again; the unused one is refunded automatically."

### Labels that were already bought

Every label either app buys is recorded in the label journal shared with the
IBP label watcher (`labels.jsonl` in `%LOCALAPPDATA%\ibp-printing`,
`~/.local/state/ibp-printing` on Linux), tagged `shippy` or `shippy-gui`,
with what happened to it: printed, queued in `to-print\`, waiting at the
printer (check printer) or refunded. At startup and after each shipment,
shippy prints `N label(s) waiting to print` when labels are queued or waiting
at the printer; shippy-gui shows "Waiting to print: N". Neither app asks
about possible duplicates: shipping several boxes to one address or unit is
normal, and an unused label is refunded automatically.

### Logs

Every discovery pass and print attempt is logged verbosely to

- Windows: `%LOCALAPPDATA%\ibp-printing\logs`
- Linux: `~/.local/state/ibp-printing/logs` (or `$XDG_STATE_HOME/ibp-printing/logs`)

shippy writes `printer-shippy.log` (human-readable) and `printer-shippy.jsonl`
(one JSON object per line), shippy-gui `printer-shippy-gui.log` and
`printer-shippy-gui.jsonl`; other IBP apps write their own `printer-<app>`
files in the same folder (`shippy diagnose-printer` writes `printer-diag.*`).
Printer messages at INFO and above also reach shippy-gui's own log file
(`ui.log_file`). Collect both files after any printing incident.

Each app also writes every warning and error it logs, from any part of the
app, to `errors-shippy.jsonl` or `errors-shippy-gui.jsonl` in the same
folder (one JSON object per line, in ibp-printing's format with the app and
its version). The stations' log upload copies the folder to the IBP server,
where a weekly digest sums these up. Every error a volunteer is shown is
logged there with its exception; normal answers (an unknown request code, a
search that found nothing, a refused setting) are not, and requests are
named by their code, never by the inmate's name or address. Uncaught
exceptions, including ones in shippy-gui's Qt slots and worker threads, are
logged too (Ctrl+C isn't). At startup each app logs `shippy starting` or
`shippy-gui starting` to its printer log with its version: the package
version plus the git commit uv installed it from (e.g. `0.1.0+gb8ac3af`).

### Troubleshooting the label printer

If shippy shows **NO LABEL PRINTER FOUND**, shippy-gui doesn't list the
printer, or labels keep going to `to-print\`, even though the printer is
powered and connected, click **Refresh** (shippy-gui), then capture a
snapshot of the printer and USB state. It needs no config file:

```
shippy diagnose-printer
```

Or via `uvx`:

```
uvx --from git+https://github.com/insidebooksproject/shippy.git@deploy shippy diagnose-printer
```

(`diagnose-printers`, ibp-printing's `ibp-print-diag` under the name
shippy-gui's docs used, prints the same report.) Run it **while the problem
is happening** and send back the output together with the log files above.
It reports each direct USB printer and, for every print queue, each detection
check (name `VID:PID` suffix, USB device present and healthy, queue status)
and whether the queue would be used, followed by the USB devices the system
sees and, on Windows, recent PrintService events.

## Development

Install Python 3.12+ and [uv](https://github.com/astral-sh/uv), then in a
clone of this repo:

```
uv venv
source .venv/bin/activate
uv sync --all-extras
uv run pre-commit install
```

On Windows, use `.venv\Scripts\activate`. `uv sync` installs the `dev` group
too (black, mypy, pylint, pytest, and PySide6 for the shippy-gui tests).
Nothing platform-specific is needed: on Windows `pywin32` and `WMI` come in
with ibp-printing, and on Linux printing goes directly over USB (install
`ibp-printing`'s udev rule once; see its README).

The code is one package, `src/shippy/`:

- `shippy.core`: the code both apps share; it never imports Qt or
  prompt-toolkit.
- `shippy.cli`: the CLI (`shippy`; questionary prompts).
- `shippy.gui`: shippy-gui (`shippy-gui`; Qt widgets and workers, and its
  own non-Qt logic in `shippy.gui.core`).

Run the checks as CI does (on Ubuntu and Windows; the pre-commit hooks run
the same):

```
uv run black --check src tests
uv run pylint src
uv run mypy src
uv run pytest
```

The shippy-gui tests run Qt offscreen by themselves (`QT_QPA_PLATFORM`; set
it to something else to watch them).

To try a CLI change without printing, pass `--preview` to open each label in
an image viewer instead:

```
shippy --preview --config config.ini manual
```

**`--preview` still buys real postage**, and shippy-gui has no test or
preview mode. For development, put an EasyPost **test** API key (from the
EasyPost dashboard) in your config so no real postage is purchased.

`ibp-printing` is pinned to a release tag of
[printing](https://github.com/insidebooksproject/printing) in `pyproject.toml`
(`[tool.uv.sources]`). To develop both together, temporarily point it at a
checkout in `../printing` with `{ path = "../printing", editable = true }`.
Tag and push a new ibp-printing release before pinning it here, or the
stations fail to install the apps.

Checks, conventions and the rules that must be preserved are in
[CLAUDE.md](CLAUDE.md).

### Releasing

`main` and `deploy` stay at the same tip. Merge feature branches straight
into `main` (no pull requests), test, then release by fast-forwarding
`deploy` to it:

```
git push origin main:deploy
```

The shipping laptops run `@deploy` with `uvx` at every launch, and the kiosk
image installs the apps from `deploy` as uv tools, so both pick up the
release at the next launch. Never commit to `deploy` directly. To roll back,
push the previous commit to `deploy` with `--force-with-lease`.

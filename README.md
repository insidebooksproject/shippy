# shippy

`shippy` is the command-line app the Inside Books Project (IBP) shipping
stations use to print shipping labels for books sent to people incarcerated in
Texas. It gets recipient and return addresses from the IBP server, buys the
cheapest USPS postage through the EasyPost API, and prints the label, with the
IBP logo, on a USB label printer through the shared
[`ibp-printing`](https://github.com/insidebooksproject/printing) library. A
label that cannot reach any printer is saved to a print queue folder instead of
being thrown away (see [When a label does not print](#when-a-label-does-not-print)).

The stations use its `individual` and `bulk` modes; packages to a typed
address go through [shippy-gui](https://github.com/insidebooksproject/shippy-gui).

## About Inside Books Project

Inside Books Project is an Austin-based community service volunteer organization that sends free reading materials to people incarcerated in Texas, and also publishes resource guides and short-form instructional pamphlets. Inside Books is the only books-to-prisoners program in Texas, where more than 120,000 people are behind bars. Inside Books Project works to promote reading, literacy, and education among incarcerated individuals and to educate the general public on issues of incarceration.

## Configuration

shippy needs a configuration file for the IBP server, EasyPost and Google Maps.

1.  Create a `config.ini` file (see `sample.ini` for a full example).
2.  Populate it with your API keys and the server URL:

    ```
    [ibp]
    url = http://192.168.1.156/api

    [easypost]
    apikey = your_easypost_api_key_here

    [googlemaps]
    apikey = your_googlemaps_api_key_here
    ```

    - `ibp.url`: The base URL of the IBP backend API. The nginx-prefixed
      form (`http://host/api`) and the direct form (`http://host:8000`)
      both work. No IBP API key is needed; an old `apikey` line is ignored.
    - `easypost.apikey`: Your EasyPost API key.
    - `googlemaps.apikey`: Your Google Maps API key (address autocompletion
      in `manual` mode). The section is required in every mode.
    - `[parcel]` (optional): the declared box in inches. `length`, `width`
      and `height` (default 20 x 14 x 10) are the box used unless the
      volunteer says the box is small; `small_length`, `small_width` and
      `small_height` (default 12 x 12 x 12) are the small box, which must be
      whole inches, exactly one cubic foot, with no side over 22.

    The return address and the recipient name for unit (bulk) shipments
    (`ATTN: MAILROOM STAFF`) are not set in `config.ini`: shippy reads them
    from the server's `/shipping-settings`, which volunteers can edit in the
    IBP web app.

## Running shippy

`--config` is required for every shipping mode. The stations run the
`deploy` branch straight from GitHub with `uvx` (see [Releasing](#releasing)):

```
uvx --from git+https://github.com/insidebooksproject/shippy.git@deploy shippy --config path/to/your/config.ini <shipping_type>
```

**Example:**

```
uvx --from git+https://github.com/insidebooksproject/shippy.git@deploy shippy --config config.ini bulk
```

The shipping laptops' desktop shortcuts run this with
`--config C:\Users\insid\config.ini` and `bulk` or `individual`.

To wrap the above in a powershell command, you can do the following:

```
powershell.exe -NoExit -Command "& { & 'uvx' --from 'git+https://github.com/insidebooksproject/shippy.git@deploy' 'shippy' --config 'C:\path\to\your\config.ini' 'bulk' }"
```

From a local checkout (see [Development](#development)), run `shippy` or
`python -m shippy` with the same arguments:

```
shippy --config config.ini individual
```

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
- `manual`: For typing the address, with Google Maps autocompletion.

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
e.g. `ibp1:unit:Texas:BETO`), or `ibp1:manual` (`manual`, an older server
that sends no request code, or anything unexpected). It is built from data
already in hand and never stops a purchase.

## Label printers

Printing is handled by `ibp-printing`. A supported printer (the PM2411BT the
shipping laptops use) is printed to directly over USB, with no print queue or
naming rule, and is tried first. Any other printer is used through a print
queue (Windows, or CUPS on Linux) only when **both** of these hold:

1. The queue name ends in the printer's USB `VID:PID`, separated from the rest of
   the name by a space, tab, `_` or `-` — e.g. `DYMO LabelWriter 450 0922:0028`.
   On Windows only local print queues are considered (USB label printers are
   local; network printer connections are skipped so a dead print server cannot
   stall printing).
2. A USB device with that `VID:PID` is currently plugged in.

If several printers qualify, healthy, problem-free and default queues are tried
first; if one fails before the job is spooled, the next one is tried. After
spooling, shippy follows the job for up to 30 seconds.

### No label printer

At startup, and again before each purchase, shippy checks for a usable label
printer. If there is none it shows `NO LABEL PRINTER FOUND` and carries on by
itself as soon as a printer is ready. Pressing Enter continues without a
printer (labels are then saved for the label watcher, below). Ctrl+C at
startup quits shippy with exit status 130, so a launcher such as the kiosk's
can tell it from a failure; before a purchase it cancels only that shipment,
and no postage is bought. `--preview` skips this check.

### When a label does not print

Unused labels are refunded automatically: a weekly job on the IBP server
refunds every label USPS never scanned (EasyPost allows this within 30 days
of purchase). So shippy doesn't stop volunteers over an occasional extra
label, and never sends them to EasyPost to refund one.

What shippy does once postage has been bought:

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

  and carries on with the next package. Only if the label cannot even be
  saved is the postage refunded right away (shippy says so).
- **The label was sent to a printer but the queue reported a problem**, or it
  could not be confirmed that the job reached the printer, or printing failed
  with an unexpected error: the label may well still print, so it is neither
  refunded nor queued again. shippy warns that it may not have printed and
  says: "Check the printer. If no label came out, create it again; the unused
  one is refunded automatically."

### Labels that were already bought

Every label shippy buys is recorded in the label journal shared with
shippy-gui and the IBP label watcher (`labels.jsonl` in
`%LOCALAPPDATA%\ibp-printing`, `~/.local/state/ibp-printing` on Linux), with
what happened to it: printed, queued in `to-print\`, waiting at the printer
(check printer) or refunded. At startup and after each shipment, shippy
prints `N label(s) waiting to print` when labels are queued or waiting at
the printer. shippy doesn't ask about possible duplicates: shipping several
boxes to one unit is normal, and an unused label is refunded automatically.

### Logs

Every discovery pass and print attempt is logged verbosely to

- Windows: `%LOCALAPPDATA%\ibp-printing\logs`
- Linux: `~/.local/state/ibp-printing/logs` (or `$XDG_STATE_HOME/ibp-printing/logs`)

shippy writes `printer-shippy.log` (human-readable) and `printer-shippy.jsonl`
(one JSON object per line); other IBP apps write their own `printer-<app>` files
in the same folder (`shippy diagnose-printer` writes `printer-diag.*`).
Collect both after any printing incident.

## Troubleshooting the label printer

If shippy shows **NO LABEL PRINTER FOUND**, or labels keep going to
`to-print\`, even though the printer is powered and connected, run the
`diagnose-printer` command to capture a snapshot of the printer and USB state.
It needs no config file:

```
shippy diagnose-printer
```

Or via `uvx`:

```
uvx --from git+https://github.com/insidebooksproject/shippy.git@deploy shippy diagnose-printer
```

Run it **while the problem is happening** and send back the output together with
the log files above. It reports each direct USB printer and, for every print
queue, each detection check (name `VID:PID` suffix, USB device present and
healthy, queue status) and whether the queue would be used, followed by the USB
devices the system sees and, on Windows, recent PrintService events.

## Development

Install [uv](https://github.com/astral-sh/uv), then in a clone of this repo:

```
uv venv
source .venv/bin/activate
uv sync
```

On Windows, use `.venv\Scripts\activate`. Run the tests, formatting, lint and
type checks as CI does:

```
uv run pytest
uv run black --check shippy
uv run pylint shippy
uv run mypy shippy
```

To try a change without printing, pass `--preview` to open each label in an
image viewer instead:

```
shippy --preview --config config.ini manual
```

**`--preview` still buys real postage.** It only skips the printer. For
development, put an EasyPost **test** API key (from the EasyPost dashboard) in
your config so no real postage is purchased.

`ibp-printing` is pinned to a release tag of
[printing](https://github.com/insidebooksproject/printing) in `pyproject.toml`
(`[tool.uv.sources]`). To develop both together, temporarily point it at a
checkout in `../printing` with `{ path = "../printing", editable = true }`.
Tag and push a new ibp-printing release before pinning it here, or the
stations fail to install shippy.

### Releasing

`main` and `deploy` stay at the same tip. Merge feature branches straight
into `main` (no pull requests), test, then release by fast-forwarding
`deploy` to it:

```
git push origin main:deploy
```

The shipping laptops run `@deploy` with `uvx` at every launch, and the kiosk
image installs shippy from `deploy` as a uv tool, so both pick up the release
at the next launch. Never commit to `deploy` directly. To roll back, push
the previous commit to `deploy` with `--force-with-lease`.

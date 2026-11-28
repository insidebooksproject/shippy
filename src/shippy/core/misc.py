"""The label image: download a bought label and stamp the IBP logo on it."""

import os
import tempfile
import contextlib
import urllib.request
from pathlib import Path

from PIL import Image

# The IBP logo stamped on every label.
LOGO_PATH = Path(__file__).parent / "assets" / "logo.jpg"

# Where the logo goes on a 4x6 label (pixels): its lower-right area.
LOGO_POSITION = (450, 425)


@contextlib.contextmanager
def build_tempfile(*args, **kwargs):
    """Build a tempfile without opening it."""
    # Create before the try: if NamedTemporaryFile itself fails there is no file
    # to remove, and running the finally anyway raised UnboundLocalError,
    # replacing the real error (bad dir, permissions, disk full) with a
    # confusing one.
    tmp = tempfile.NamedTemporaryFile(*args, **kwargs, delete=False)
    try:
        tmp.close()
        yield tmp
    finally:
        os.remove(tmp.name)


def grab_png_from_url(url: str):
    """Grab a PNG image from a URL."""
    with build_tempfile(suffix=".png") as tmpfile:
        urllib.request.urlretrieve(url, tmpfile.name)
        img = Image.open(tmpfile.name)
        img.load()
        return img


def load_logo() -> Image.Image:
    """Open the IBP logo."""
    return Image.open(LOGO_PATH)


def add_logo(label: Image.Image, logo: Image.Image) -> None:
    """Stamp ``logo`` on a label image in place."""
    label.paste(logo, LOGO_POSITION)

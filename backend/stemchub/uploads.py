"""The uploader's rules: a file goes into Nextcloud only under a path the sync understands.

Instead of asking people to type  INDUZELL/U3/day05/...  correctly, the user picks a run and a day and the
path is built here. Everything is checked before a single byte is uploaded.
"""

import re
from pathlib import PurePosixPath

from stemchub.naming import parse_image_path

CZI_MAGIC = b"ZISRAWFILE"  # first bytes of every Zeiss CZI file
DAY_MIN, DAY_MAX = -5, 60
_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,195}\.czi$", re.IGNORECASE)


class UploadRejected(ValueError):
    """The file or its run/day breaks a rule; the message says which, in words the user can act on."""


def check_run_id(run_id: str) -> str:
    run = (run_id or "").strip().upper()
    if not _RUN_RE.match(run):
        raise UploadRejected("Run must be letters, digits, '-' or '_' (e.g. U3), at most 64 characters.")
    return run


def check_day(day: int) -> int:
    if not DAY_MIN <= day <= DAY_MAX:
        raise UploadRejected(f"Day must be between {DAY_MIN} and {DAY_MAX}.")
    return day


def check_image_name(filename: str) -> str:
    name = PurePosixPath((filename or "").replace("\\", "/")).name.strip()  # never a path from the browser
    if not name.lower().endswith(".czi"):
        raise UploadRejected(f"'{name or filename}' is not a .czi file.")
    if not _NAME_RE.match(name):
        raise UploadRejected(f"File name '{name}' may only contain letters, digits, spaces and . _ - ( ) +")
    return name


def check_czi_header(first_bytes: bytes, name: str) -> None:
    if not first_bytes.startswith(CZI_MAGIC):
        raise UploadRejected(f"'{name}' ends in .czi but is not a Zeiss CZI file.")


def day_folder(day: int) -> str:
    return f"day{day:03d}" if day < 0 else f"day{day:02d}"  # day-02, day05


def image_path(root: str, run_id: str, day: int, filename: str) -> str:
    path = f"{root.strip('/')}/{run_id}/{day_folder(day)}/{filename}"
    ref = parse_image_path(path, root)
    if ref is None or (ref.run_id, ref.day) != (run_id, day):
        raise RuntimeError(f"uploader and sync disagree on the naming rule for {path}")
    return path


def process_path(root: str, run_id: str) -> str:
    return f"{root.strip('/')}/{run_id}/process.csv"

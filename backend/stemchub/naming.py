"""The shared-key convention for files in Nextcloud.

    <root>/<run_id>/day<NN>/<anything>.czi     -> one microscopy image of run <run_id> on day <NN>
    <root>/<run_id>/process.csv                -> process values (pH, glucose, ...) of run <run_id>

Days may be negative (the expansion phase starts at day -2), e.g. "day-02".
"""

import re
from dataclasses import dataclass

_RUN = r"(?P<run>[A-Za-z0-9][A-Za-z0-9_-]{0,63})"
_IMAGE_RE = re.compile(rf"^{_RUN}/day(?P<day>-?\d{{1,3}})/(?P<file>[^/]+\.czi)$", re.IGNORECASE)
_PROCESS_RE = re.compile(rf"^{_RUN}/process\.csv$", re.IGNORECASE)


@dataclass(frozen=True)
class ImageRef:
    run_id: str
    day: int
    filename: str


def _relative(path: str, root: str) -> str | None:
    path, root = path.strip("/"), root.strip("/")
    if not path.startswith(root + "/"):
        return None
    return path[len(root) + 1 :]


def parse_image_path(path: str, root: str) -> ImageRef | None:
    rel = _relative(path, root)
    m = _IMAGE_RE.match(rel) if rel else None
    if not m:
        return None
    return ImageRef(run_id=m["run"].upper(), day=int(m["day"]), filename=m["file"])


def parse_process_path(path: str, root: str) -> str | None:
    """Returns the run id if the path is a run's process.csv."""
    rel = _relative(path, root)
    m = _PROCESS_RE.match(rel) if rel else None
    return m["run"].upper() if m else None

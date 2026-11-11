"""OMERO through omero-py (BlitzGateway) and the OMERO CLI importer.

Reading pixels, key-value annotations and thumbnails use the Python API; importing a file uses
`omero import` (Bio-Formats, Java) — the same importer OMERO.insight uses.
"""

import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from stemchub.config import Settings

NAMESPACE = "stemcdatahub.induzell"  # namespace of our key-value annotations


class OmeroError(RuntimeError):
    pass


@dataclass
class ImageInfo:
    id: int
    name: str
    size_x: int
    size_y: int
    size_z: int
    size_c: int
    channels: list[str]
    pixel_size_um: float | None


@contextmanager
def connect(settings: Settings):
    from omero.gateway import BlitzGateway

    conn = BlitzGateway(
        settings.omero_user, settings.omero_password, host=settings.omero_host, port=settings.omero_port, secure=True
    )
    if not conn.connect():
        raise OmeroError(f"cannot log in to OMERO at {settings.omero_host}:{settings.omero_port}")
    try:
        conn.SERVICE_OPTS.setOmeroGroup("-1")  # read across all groups the user can see
        yield conn
    finally:
        conn.close()


@contextmanager
def in_group(conn, group_id: int):
    """OMERO refuses writes with omero.group=-1: switch to the owning group for the duration of a write."""
    conn.SERVICE_OPTS.setOmeroGroup(str(group_id))
    try:
        yield conn.SERVICE_OPTS
    finally:
        conn.SERVICE_OPTS.setOmeroGroup("-1")


def _group_of(obj) -> int:
    return obj.getDetails().getGroup().getId()


def ensure_dataset(conn, project_name: str, dataset_name: str) -> int:
    """Finds (or creates) Project <project_name> / Dataset <dataset_name>, returns the dataset id."""
    import omero.model
    from omero.rtypes import rstring

    update = conn.getUpdateService()
    project = next(iter(conn.getObjects("Project", attributes={"name": project_name})), None)
    if project is None:
        p = omero.model.ProjectI()
        p.setName(rstring(project_name))
        with in_group(conn, conn.getEventContext().groupId) as ctx:
            project_id = update.saveAndReturnObject(p, ctx).getId().getValue()
        project = conn.getObject("Project", project_id)

    for ds in project.listChildren():
        if ds.getName() == dataset_name:
            return ds.getId()

    with in_group(conn, _group_of(project)) as ctx:
        d = omero.model.DatasetI()
        d.setName(rstring(dataset_name))
        dataset_id = update.saveAndReturnObject(d, ctx).getId().getValue()
        link = omero.model.ProjectDatasetLinkI()
        link.setParent(omero.model.ProjectI(project.getId(), False))
        link.setChild(omero.model.DatasetI(dataset_id, False))
        update.saveObject(link, ctx)
    return dataset_id


def find_image_in_dataset(conn, dataset_id: int, name: str) -> int | None:
    """An image with this name already in the dataset (e.g. imported before a crash) — reuse it, don't import twice."""
    dataset = conn.getObject("Dataset", dataset_id)
    found = [img.getId() for img in dataset.listChildren() if img.getName() == name] if dataset else []
    return max(found) if found else None


def import_file(settings: Settings, path: Path, dataset_id: int, timeout: int = 900) -> list[int]:
    """Runs `omero import` and returns the new image ids."""
    cmd = [
        "omero",
        "import",
        "-s",
        settings.omero_host,
        "-p",
        str(settings.omero_port),
        "-u",
        settings.omero_user,
        "-w",
        settings.omero_password,
        "-d",
        str(dataset_id),
        "--output",
        "ids",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        raise OmeroError("omero import failed: " + " | ".join(tail))
    ids = [int(x) for x in re.findall(r"Image:(\d+)", proc.stdout)]
    if not ids:
        raise OmeroError("omero import reported no images: " + proc.stdout[-300:])
    return ids


def image_info(conn, image_id: int) -> ImageInfo:
    img = conn.getObject("Image", image_id)
    if img is None:
        raise OmeroError(f"image {image_id} not found")
    size = img.getPixelSizeX()  # micrometres (default unit)
    return ImageInfo(
        id=image_id,
        name=img.getName(),
        size_x=img.getSizeX(),
        size_y=img.getSizeY(),
        size_z=img.getSizeZ(),
        size_c=img.getSizeC(),
        channels=[c or f"C{i}" for i, c in enumerate(img.getChannelLabels())],
        pixel_size_um=float(size) if size else None,
    )


def read_stack(conn, image_id: int, t: int = 0) -> np.ndarray:
    """All channels and z-planes of one timepoint as (C, Z, Y, X)."""
    img = conn.getObject("Image", image_id)
    pixels = img.getPrimaryPixels()
    size_c, size_z = img.getSizeC(), img.getSizeZ()
    zct = [(z, c, t) for c in range(size_c) for z in range(size_z)]
    planes = list(pixels.getPlanes(zct))
    return np.stack(planes).reshape(size_c, size_z, img.getSizeY(), img.getSizeX())


def set_key_values(conn, image_id: int, pairs: list[tuple[str, str]]) -> None:
    """Replaces our (namespaced) key-value annotation on the image; other annotations are left alone."""
    from omero.gateway import MapAnnotationWrapper

    img = conn.getObject("Image", image_id)
    old = [a.getId() for a in img.listAnnotations(ns=NAMESPACE)]
    with in_group(conn, _group_of(img)):
        if old:
            conn.deleteObjects("Annotation", old, wait=True)
        ann = MapAnnotationWrapper(conn)
        ann.setNs(NAMESPACE)
        ann.setValue([[k, v] for k, v in pairs])
        ann.save()
        img.linkAnnotation(ann)


def write_mask_rois(conn, image_id: int, labels: np.ndarray, dead_labels: set[int]) -> int:
    """Saves one ROI per nucleus (mask shape) on the image. Returns the number of ROIs."""
    import omero.model
    from omero.rtypes import rint, rstring
    from omero_rois import masks_from_label_image

    img = conn.getObject("Image", image_id)
    old = conn.getRoiService().findByImage(image_id, None, conn.SERVICE_OPTS).rois

    alive, dead = (60, 220, 120, 128), (240, 60, 200, 128)
    masks = masks_from_label_image(labels, rgba=None, z=None, c=None, t=None, raise_on_no_mask=False)
    rois = []
    for label, mask in enumerate(masks, start=1):
        if mask is None:
            continue
        r, g, b, a = dead if label in dead_labels else alive
        rgba = (r << 24) | (g << 16) | (b << 8) | a
        mask.setFillColor(rint(rgba - (1 << 32) if rgba >= (1 << 31) else rgba))  # OMERO wants signed int32
        mask.setTextValue(rstring(f"{'dead' if label in dead_labels else 'alive'} #{label}"))
        roi = omero.model.RoiI()
        roi.setImage(img._obj)
        roi.addShape(mask)
        rois.append(roi)
    with in_group(conn, _group_of(img)) as ctx:
        if old:
            conn.deleteObjects("Roi", [r.getId().getValue() for r in old], wait=True)
        if rois:
            conn.getUpdateService().saveArray(rois, ctx)
    return len(rois)


def thumbnail(conn, image_id: int, size: int = 256) -> bytes:
    """Small version of the max projection. (OMERO's own thumbnail shows only the middle z-plane, which is
    often nearly empty for aggregates — and would not match the projection shown in the viewer.)"""
    import io

    from PIL import Image as PILImage

    pic = PILImage.open(io.BytesIO(render_projection(conn, image_id)))
    pic.thumbnail((size, size))
    out = io.BytesIO()
    pic.convert("RGB").save(out, format="JPEG", quality=85)
    return out.getvalue()


def render_projection(conn, image_id: int) -> bytes:
    """Maximum-intensity projection over z, rendered with the image's channel settings (JPEG)."""
    img = conn.getObject("Image", image_id)
    if img is None:
        raise OmeroError(f"image {image_id} not found")
    if img.getSizeZ() > 1:
        img.setProjection("intmax")
    return img.renderJpeg(0, 0, compression=0.9)


def web_url(settings: Settings, image_id: int) -> str:
    return f"{settings.omero_web_public_url.rstrip('/')}/webclient/?show=image-{image_id}"

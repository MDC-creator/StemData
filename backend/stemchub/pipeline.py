"""The data flow, step by step. Called by the worker tasks; every function takes a DB session and settings.

sync_nextcloud   new .czi in Nextcloud  -> Image rows (status "new");  process.csv -> Measurement rows
process_image    download -> import into OMERO -> key-values -> live/dead analysis -> results -> ROIs
sync_elabftw     eLabFTW experiments with a run_id -> Run rows (title, cell line, protocol)
writeback        summary + link back into the eLabFTW entry, results CSV into Nextcloud
"""

import csv
import io
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image as PILImage
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stemchub import analysis
from stemchub.config import Settings
from stemchub.connectors import omero as om
from stemchub.connectors.elabftw import ElabClient
from stemchub.connectors.nextcloud import NextcloudClient
from stemchub.models import Image, ImageResult, Measurement, Nucleus, Run, SourceFile
from stemchub.naming import parse_image_path, parse_process_path
from stemchub.process_csv import parse_process_csv

log = logging.getLogger(__name__)


def ensure_run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        run = Run(id=run_id)
        session.add(run)
        session.flush()
    return run


def cache_path(settings: Settings, kind: str, name: str) -> Path:
    p = Path(settings.cache_dir) / kind / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- Nextcloud -> DB


def sync_nextcloud(session: Session, settings: Settings) -> dict:
    """Registers new images and (re)reads changed process.csv files. Returns ids of images to process."""
    new_images: list[int] = []
    csv_runs: list[str] = []
    skipped: list[str] = []
    with NextcloudClient(settings) as nc:
        files = nc.walk(settings.nextcloud_root)
        for f in files:
            ref = parse_image_path(f.path, settings.nextcloud_root)
            if ref:
                existing = session.scalar(select(Image).where(Image.nextcloud_path == f.path))
                if existing is None:
                    ensure_run(session, ref.run_id)
                    img = Image(
                        run_id=ref.run_id, day=ref.day, filename=ref.filename, nextcloud_path=f.path, nextcloud_etag=f.etag
                    )
                    session.add(img)
                    session.flush()
                    new_images.append(img.id)
                elif existing.nextcloud_etag != f.etag and existing.status in ("done", "error"):
                    # file was replaced: import the new version, keep the old OMERO image untouched
                    existing.nextcloud_etag, existing.status, existing.error = f.etag, "new", None
                    existing.omero_image_id = None
                    new_images.append(existing.id)
                continue

            run_id = parse_process_path(f.path, settings.nextcloud_root)
            if run_id:
                seen = session.get(SourceFile, f.path)
                if seen is None or seen.etag != f.etag:
                    import_process_csv(session, run_id, f.path, nc.read_text(f.path))
                    session.merge(SourceFile(path=f.path, etag=f.etag))
                    csv_runs.append(run_id)
                continue

            if f.path.lower().endswith((".czi", ".csv")) and "/exports/" not in f.path:
                # does not follow the naming rule: report it once (and again only if the file changes)
                seen = session.get(SourceFile, f.path)
                if seen is None or seen.etag != f.etag:
                    session.merge(SourceFile(path=f.path, etag=f.etag))
                    skipped.append(f.path)

        # everything still waiting (new now, or registered earlier and never queued) goes to the worker once
        waiting = session.scalars(select(Image).where(Image.status == "new")).all()
        for img in waiting:
            img.status = "queued"
        new_images = sorted({*new_images, *(img.id for img in waiting)})
        session.commit()
    if skipped:
        log.warning("files not following <run>/day<NN>/<file>.czi: %s", skipped[:10])
    return {"new_images": new_images, "csv_runs": csv_runs, "skipped": skipped}


def import_process_csv(session: Session, run_id: str, source: str, text: str) -> int:
    values = parse_process_csv(text)
    ensure_run(session, run_id)
    session.execute(delete(Measurement).where(Measurement.run_id == run_id))
    session.add_all(
        Measurement(run_id=run_id, day=v.day, parameter=v.parameter, value=v.value, unit=v.unit, source=source) for v in values
    )
    session.flush()
    return len(values)


# ---------------------------------------------------------------- one image, end to end


def process_image(
    session: Session,
    settings: Settings,
    image_id: int,
    get_segmenter: Callable[[], tuple[analysis.Segmenter, str]],
) -> ImageResult:
    img = session.get(Image, image_id)
    if img is None:
        raise ValueError(f"image {image_id} not in database")
    try:
        with om.connect(settings) as conn:
            if img.omero_image_id is None or conn.getObject("Image", img.omero_image_id) is None:
                img.status = "importing"
                session.commit()
                dataset_id = om.ensure_dataset(conn, settings.omero_project, img.run_id)
                if img.omero_import_etag is None:  # never finished an import: maybe it got into OMERO before a crash
                    img.omero_image_id = om.find_image_in_dataset(conn, dataset_id, img.filename)
                if img.omero_image_id is None:
                    with tempfile.TemporaryDirectory(dir=settings.cache_dir) as tmp:
                        local = Path(tmp) / img.filename
                        with NextcloudClient(settings) as nc:
                            nc.download(img.nextcloud_path, local)
                        img.omero_image_id = om.import_file(settings, local, dataset_id)[0]
                img.omero_import_etag = img.nextcloud_etag
                session.commit()  # keep the OMERO id even if a later step fails

            info = om.image_info(conn, img.omero_image_id)
            img.size_x, img.size_y, img.size_z = info.size_x, info.size_y, info.size_z
            img.channels, img.pixel_size_um = info.channels, info.pixel_size_um
            om.set_key_values(
                conn,
                img.omero_image_id,
                [
                    ("run_id", img.run_id),
                    ("day", str(img.day)),
                    ("source", f"nextcloud:{img.nextcloud_path}"),
                    ("stemcdatahub", f"{settings.public_url.rstrip('/')}/runs/{img.run_id}"),
                ],
            )

            img.status = "analyzing"
            session.commit()
            stack = om.read_stack(conn, img.omero_image_id)
            segment, name = get_segmenter()
            res = analysis.analyze_live_dead(
                stack,
                info.channels,
                info.pixel_size_um or 1.0,
                segment,
                name,
                settings.nucleus_diameter_um,
                settings.ethd_min_z,
                settings.ethd_min_ratio,
            )
            dead_labels = {n.label for n in res.nuclei if n.dead}
            if settings.write_rois:
                om.write_mask_rois(conn, img.omero_image_id, res.labels, dead_labels)

        PILImage.fromarray(analysis.outline_overlay(res.labels, dead_labels)).save(cache_path(settings, "masks", f"{img.id}.png"))
        for stale in Path(settings.cache_dir).glob(f"*/{img.id}_*"):
            stale.unlink(missing_ok=True)  # thumbnails of a replaced file

        session.execute(delete(Nucleus).where(Nucleus.image_id == img.id))
        result = session.get(ImageResult, img.id) or ImageResult(image_id=img.id)
        result.nuclei_count, result.dead_count = res.nuclei_count, res.dead_count
        result.dead_fraction, result.mean_nucleus_area_um2 = res.dead_fraction, res.mean_nucleus_area_um2
        result.aggregate_area_um2, result.segmenter, result.ethd_threshold = (
            res.aggregate_area_um2,
            res.segmenter,
            res.ethd_threshold,
        )
        result = session.merge(result)  # merge returns the persistent object; keep using that one
        session.add_all(Nucleus(image_id=img.id, **n.__dict__) for n in res.nuclei)
        img.status, img.error = "done", None
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        img = session.get(Image, image_id)
        img.status, img.error = "error", f"{type(exc).__name__}: {exc}"[:2000]
        session.commit()
        raise


# ---------------------------------------------------------------- eLabFTW


def sync_elabftw(session: Session, settings: Settings) -> tuple[list[str], list[str]]:
    """Returns (all run ids found in eLabFTW, run ids that were new or changed)."""
    with ElabClient(settings) as elab:
        runs = elab.runs()
    changed = []
    for r in runs:
        run = ensure_run(session, r.run_id)
        new = (r.title, r.cell_line, r.protocol, r.status, r.elab_id)
        if (run.title, run.cell_line, run.protocol, run.status, run.elab_id) != new:
            run.title, run.cell_line, run.protocol, run.status, run.elab_id = new
            changed.append(r.run_id)
    session.commit()
    return [r.run_id for r in runs], changed


def run_summary_rows(session: Session, run_id: str) -> list[dict]:
    rows = []
    images = session.scalars(select(Image).where(Image.run_id == run_id).order_by(Image.day, Image.filename))
    for img in images:
        r = img.result
        rows.append(
            {
                "run_id": run_id,
                "day": img.day,
                "file": img.filename,
                "omero_image_id": img.omero_image_id,
                "nuclei": r.nuclei_count if r else None,
                "dead": r.dead_count if r else None,
                "dead_fraction": round(r.dead_fraction, 4) if r else None,
                "mean_nucleus_area_um2": round(r.mean_nucleus_area_um2, 2) if r and r.mean_nucleus_area_um2 else None,
                "aggregate_area_um2": round(r.aggregate_area_um2, 1) if r and r.aggregate_area_um2 else None,
                "status": img.status,
            }
        )
    return rows


def writeback(session: Session, settings: Settings, run_id: str) -> dict:
    """Results CSV -> Nextcloud exports/;  summary + link -> eLabFTW extra fields."""
    rows = run_summary_rows(session, run_id)
    done = [r for r in rows if r["dead_fraction"] is not None]
    out: dict = {"rows": len(rows)}

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    export_path = f"{settings.nextcloud_root}/exports/{run_id}_results.csv"
    with NextcloudClient(settings) as nc:
        nc.upload(export_path, buf.getvalue().encode())
    out["nextcloud"] = export_path

    run = session.get(Run, run_id)
    if settings.elab_writeback and run and run.elab_id and done:
        latest = max(done, key=lambda r: r["day"])
        with ElabClient(settings) as elab:
            elab.set_extra_fields(
                run.elab_id,
                {
                    "StemCDataHub": {"type": "url", "value": f"{settings.public_url.rstrip('/')}/runs/{run_id}"},
                    "Images analysed": {"type": "number", "value": str(len(done))},
                    f"Dead fraction (day {latest['day']})": {
                        "type": "number",
                        "value": f"{latest['dead_fraction'] * 100:.1f}",
                        "unit": "%",
                        "units": ["%"],
                    },
                },
            )
        out["elab_id"] = run.elab_id
    return out

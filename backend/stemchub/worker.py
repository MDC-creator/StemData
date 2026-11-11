"""Background tasks (Celery). Start with:  celery -A stemchub.worker worker -B --concurrency=1

-B also runs the scheduler: Nextcloud is polled every NEXTCLOUD_POLL_SECONDS (the webhook endpoint
can trigger it sooner), eLabFTW every ELAB_SYNC_SECONDS.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache

from celery import Celery

from stemchub import analysis, pipeline
from stemchub.config import get_settings
from stemchub.db import SessionLocal, init_db
from stemchub.models import Job

log = logging.getLogger(__name__)
settings = get_settings()

app = Celery("stemchub", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "poll-nextcloud": {"task": "stemchub.worker.poll_nextcloud", "schedule": float(settings.nextcloud_poll_seconds)},
        "sync-elabftw": {"task": "stemchub.worker.sync_elabftw", "schedule": float(settings.elab_sync_seconds)},
    },
)


@app.on_after_configure.connect
def _setup(**_):
    init_db()


@lru_cache
def get_segmenter() -> tuple[analysis.Segmenter, str]:
    """Loaded once per worker process (the Cellpose model takes a few seconds to load)."""
    if settings.segmenter == "cellpose":
        return analysis.cellpose_segmenter(), "cellpose-nuclei"
    return analysis.classic_segmenter, "classic-watershed"


QUIET = "quiet"


@contextmanager
def job(kind: str):
    """Records the task in the jobs table so the UI can show what happened.

    A task sets j.status = QUIET when it found nothing to do; routine checks every minute would
    otherwise bury the real events in the Activity list.
    """
    with SessionLocal() as session:
        j = Job(kind=kind, status="running")
        session.add(j)
        session.commit()
        try:
            yield session, j
        except Exception as exc:
            session.rollback()
            j = session.get(Job, j.id)
            j.status, j.message = "error", f"{type(exc).__name__}: {exc}"[:2000]
            j.finished_at = datetime.now(UTC)
            session.commit()
            log.exception("%s failed", kind)
            # re-raise as a plain error: Celery must be able to serialise it (OMERO's Ice exceptions crash the worker)
            raise RuntimeError(j.message) from None
        if j.status == QUIET:
            session.delete(j)
        else:
            j.status, j.finished_at = "done", datetime.now(UTC)
        session.commit()


@app.task
def poll_nextcloud() -> dict:
    with job("poll_nextcloud") as (session, j):
        out = pipeline.sync_nextcloud(session, settings)
        j.message = f"{len(out['new_images'])} new image(s), process data for {out['csv_runs'] or 'no'} run(s)"
        if out["skipped"]:
            j.message += f"; {len(out['skipped'])} file(s) not following the naming rule, e.g. {out['skipped'][0]}"
        elif not out["new_images"] and not out["csv_runs"]:
            j.status = QUIET
    for image_id in out["new_images"]:
        process_image.delay(image_id)
    for run_id in out["csv_runs"]:
        writeback.delay(run_id)
    return out


@app.task
def process_image(image_id: int) -> dict:
    with job("process_image") as (session, j):
        result = pipeline.process_image(session, settings, image_id, get_segmenter)
        img = result.image
        j.message = f"{img.run_id} day {img.day} ({img.filename}): {result.nuclei_count} nuclei, {result.dead_fraction:.1%} dead"
        run_id = img.run_id
    writeback.delay(run_id)
    return {"image_id": image_id, "nuclei": result.nuclei_count}


@app.task
def sync_elabftw() -> list[str]:
    with job("sync_elabftw") as (session, j):
        runs, changed = pipeline.sync_elabftw(session, settings)
        j.message = f"{len(runs)} run(s) in eLabFTW, updated: {', '.join(changed)}"
        if not changed:
            j.status = QUIET
    return runs


@app.task
def writeback(run_id: str) -> dict:
    with job("writeback") as (session, j):
        out = pipeline.writeback(session, settings, run_id)
        j.message = f"{run_id}: results -> {out['nextcloud']}" + (f", eLabFTW #{out['elab_id']}" if "elab_id" in out else "")
    return out

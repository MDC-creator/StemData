"""REST API for the web interface.  Run:  uvicorn stemchub.api:app  — interactive docs at /api/docs."""

import hmac
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import redis
from celery import Celery
from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from stemchub import auth, uploads
from stemchub import routes_auth as auth_routes
from stemchub.config import Settings, get_settings
from stemchub.connectors import omero as om
from stemchub.connectors.elabftw import ElabClient
from stemchub.connectors.nextcloud import NextcloudClient
from stemchub.db import SessionLocal, get_session, init_db
from stemchub.models import Image, Job, Measurement, Nucleus, Run
from stemchub.process_csv import ProcessCsvError, parse_process_csv
from stemchub.schemas import (
    Health,
    ImageOut,
    JobOut,
    MeasurementOut,
    NucleusOut,
    Queued,
    RunOut,
    ServiceStatus,
    SummaryRow,
    UploadResult,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        auth.bootstrap_admin(db)
    yield


app = FastAPI(title="StemCDataHub API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)

# Everything below needs a login; uploads, re-analysis and sync also need the role "scientist".
protected = APIRouter(dependencies=[Depends(auth.current_user)])
public = APIRouter()
CSRF_HEADER, CSRF_VALUE = "X-Requested-With", "stemchub"


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Requests that change something must carry a header other websites cannot set (no CORS here), so a
    page on another site cannot make a logged-in browser upload or change data. Webhooks use their token."""
    path = request.url.path
    if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/") and not path.startswith("/api/hooks/"):
        if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return Response(f"missing {CSRF_HEADER} header", status_code=403)
    return await call_next(request)


def tasks() -> Celery:
    """Thin Celery client: sends tasks by name, so the API image does not need the analysis libraries."""
    s = get_settings()
    return Celery("stemchub", broker=s.redis_url)


def run_out(run: Run, settings: Settings) -> RunOut:
    out = RunOut.model_validate(run)
    out.image_count = len(run.images)
    out.analyzed_count = sum(1 for i in run.images if i.status == "done")
    out.days = sorted({i.day for i in run.images} | {m.day for m in run.measurements})
    if run.elab_id:
        out.elab_url = f"{settings.elab_public_url.rstrip('/')}/experiments.php?mode=view&id={run.elab_id}"
    return out


def image_out(img: Image, settings: Settings) -> ImageOut:
    out = ImageOut.model_validate(img)
    if img.omero_image_id:
        out.omero_url = om.web_url(settings, img.omero_image_id)
    return out


# ------------------------------------------------------------------ health


def _check(name: str, fn) -> ServiceStatus:
    try:
        return ServiceStatus(name=name, ok=True, detail=fn())
    except Exception as exc:  # report, never crash the health endpoint
        return ServiceStatus(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}"[:300])


@protected.get("/api/health", response_model=Health, tags=["system"])
def health(session: Session = Depends(get_session), settings: Settings = Depends(get_settings)) -> Health:
    def db():
        session.execute(text("select 1"))
        return "connected"

    def queue():
        redis.Redis.from_url(settings.redis_url, socket_timeout=3).ping()
        return "connected"

    def omero():
        with om.connect(settings) as conn:
            return f"logged in as {conn.getUser().getName()}"

    def nextcloud():
        with NextcloudClient(settings, timeout=5) as nc:
            st = nc.status()
            nc.list_dir(settings.nextcloud_root)
            return f"version {st.get('versionstring')}, folder /{settings.nextcloud_root} readable"

    def elab():
        with ElabClient(settings, timeout=5) as e:
            return f"API key of {e.me().get('fullname')}"

    services = [
        _check("database", db),
        _check("queue", queue),
        _check("omero", omero),
        _check("nextcloud", nextcloud),
        _check("elabftw", elab),
    ]
    return Health(ok=all(s.ok for s in services), services=services)


# ------------------------------------------------------------------ runs


def _load_run(session: Session, run_id: str) -> Run:
    run = session.scalar(
        select(Run).where(Run.id == run_id.upper()).options(selectinload(Run.images), selectinload(Run.measurements))
    )
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    return run


@protected.get("/api/runs", response_model=list[RunOut], tags=["runs"])
def list_runs(session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    runs = session.scalars(select(Run).options(selectinload(Run.images), selectinload(Run.measurements)).order_by(Run.id))
    return [run_out(r, settings) for r in runs]


@protected.get("/api/runs/{run_id}", response_model=RunOut, tags=["runs"])
def get_run(run_id: str, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    return run_out(_load_run(session, run_id), settings)


@protected.get("/api/runs/{run_id}/measurements", response_model=list[MeasurementOut], tags=["runs"])
def run_measurements(run_id: str, session: Session = Depends(get_session)):
    _load_run(session, run_id)
    return session.scalars(
        select(Measurement).where(Measurement.run_id == run_id.upper()).order_by(Measurement.parameter, Measurement.day)
    ).all()


@protected.get("/api/runs/{run_id}/images", response_model=list[ImageOut], tags=["runs"])
def run_images(run_id: str, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    _load_run(session, run_id)
    images = session.scalars(
        select(Image)
        .where(Image.run_id == run_id.upper())
        .options(selectinload(Image.result))
        .order_by(Image.day, Image.filename)
    )
    return [image_out(i, settings) for i in images]


@protected.get("/api/summary", response_model=list[SummaryRow], tags=["runs"])
def summary(session: Session = Depends(get_session)):
    """Per run and day: image results next to that day's process values (pH, glucose, ...)."""
    images = session.scalars(select(Image).options(selectinload(Image.result)))
    groups: dict[tuple[str, int], list[Image]] = defaultdict(list)
    for img in images:
        groups[(img.run_id, img.day)].append(img)
    process: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    for m in session.scalars(select(Measurement)):
        process[(m.run_id, m.day)][m.parameter] = m.value

    rows = []
    for key in sorted(set(groups) | set(process)):
        done = [i.result for i in groups.get(key, []) if i.result]
        nuclei = sum(r.nuclei_count for r in done)
        dead = sum(r.dead_count for r in done)
        areas = [r.mean_nucleus_area_um2 for r in done if r.mean_nucleus_area_um2]
        rows.append(
            SummaryRow(
                run_id=key[0],
                day=key[1],
                images=len(groups.get(key, [])),
                nuclei=nuclei,
                dead_fraction=dead / nuclei if nuclei else None,
                mean_nucleus_area_um2=sum(areas) / len(areas) if areas else None,
                process=process.get(key, {}),
            )
        )
    return rows


# ------------------------------------------------------------------ images


def _image(session: Session, image_id: int) -> Image:
    img = session.get(Image, image_id)
    if img is None:
        raise HTTPException(404, f"image {image_id} not found")
    return img


@protected.get("/api/images/{image_id}", response_model=ImageOut, tags=["images"])
def get_image(image_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    return image_out(_image(session, image_id), settings)


@protected.get("/api/images/{image_id}/nuclei", response_model=list[NucleusOut], tags=["images"])
def image_nuclei(image_id: int, session: Session = Depends(get_session)):
    _image(session, image_id)
    return session.scalars(select(Nucleus).where(Nucleus.image_id == image_id).order_by(Nucleus.label)).all()


def _cached(settings: Settings, kind: str, name: str, produce) -> bytes:
    """Rendered images come from OMERO once, then from our file cache."""
    path = Path(settings.cache_dir) / kind / name
    if path.exists():
        return path.read_bytes()
    data = produce()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


_IMG_CACHE = {"Cache-Control": "public, max-age=3600"}


@protected.get("/api/images/{image_id}/thumbnail", tags=["images"])
def image_thumbnail(
    image_id: int,
    size: int = Query(256, ge=32, le=1024),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    img = _image(session, image_id)
    if not img.omero_image_id:
        raise HTTPException(409, "image not yet in OMERO")

    def produce():
        with om.connect(settings) as conn:
            return om.thumbnail(conn, img.omero_image_id, size)

    return Response(_cached(settings, "thumbs", f"{img.id}_{size}.jpg", produce), media_type="image/jpeg", headers=_IMG_CACHE)


@protected.get("/api/images/{image_id}/preview", tags=["images"])
def image_preview(image_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    """Full-size max-intensity projection, rendered by OMERO."""
    img = _image(session, image_id)
    if not img.omero_image_id:
        raise HTTPException(409, "image not yet in OMERO")

    def produce():
        with om.connect(settings) as conn:
            return om.render_projection(conn, img.omero_image_id)

    return Response(_cached(settings, "preview", f"{img.id}_max.jpg", produce), media_type="image/jpeg", headers=_IMG_CACHE)


@protected.get("/api/images/{image_id}/mask", tags=["images"])
def image_mask(image_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    """Transparent PNG with nucleus outlines (green alive, magenta dead), same size as the preview."""
    _image(session, image_id)
    path = Path(settings.cache_dir) / "masks" / f"{image_id}.png"
    if not path.exists():
        raise HTTPException(404, "no analysis yet")
    return Response(path.read_bytes(), media_type="image/png")


@protected.post(
    "/api/images/{image_id}/reprocess", dependencies=[Depends(auth.require_scientist)], response_model=Queued, tags=["images"]
)
def reprocess(image_id: int, session: Session = Depends(get_session)):
    img = _image(session, image_id)
    img.status = "queued"
    session.commit()
    tasks().send_task("stemchub.worker.process_image", args=[image_id])
    return Queued(queued=[f"process_image {image_id}"])


# ------------------------------------------------------------------ uploader
# The user picks run + day; the path in Nextcloud is built from the naming rule, so it can't be wrong.


@protected.post(
    "/api/uploads/image", dependencies=[Depends(auth.require_scientist)], response_model=UploadResult, tags=["uploads"]
)
def upload_image(
    run_id: str = Form(...),
    day: int = Form(...),
    replace: bool = Form(False),
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    try:
        run = uploads.check_run_id(run_id)
        uploads.check_day(day)
        name = uploads.check_image_name(file.filename or "")
        uploads.check_czi_header(file.file.read(len(uploads.CZI_MAGIC)), name)
        file.file.seek(0)  # the header check read the first bytes; upload the whole file
    except uploads.UploadRejected as exc:
        raise HTTPException(422, str(exc)) from None
    path = uploads.image_path(settings.nextcloud_root, run, day, name)
    with NextcloudClient(settings, timeout=600) as nc:
        if not replace and nc.exists(path):
            raise HTTPException(409, f"{path} already exists. Tick 'replace' to upload a new version.")
        nc.upload(path, file.file)
    tasks().send_task("stemchub.worker.poll_nextcloud")  # don't wait for the next scheduled check
    return UploadResult(path=path, run_id=run, day=day, message="uploaded; import and analysis start now")


@protected.post(
    "/api/uploads/process", dependencies=[Depends(auth.require_scientist)], response_model=UploadResult, tags=["uploads"]
)
def upload_process_csv(run_id: str = Form(...), file: UploadFile = File(...), settings: Settings = Depends(get_settings)):
    try:
        run = uploads.check_run_id(run_id)
        raw = file.file.read(5_000_001)
        if len(raw) > 5_000_000:
            raise uploads.UploadRejected("process.csv is larger than 5 MB; is it the right file?")
        values = parse_process_csv(raw.decode("utf-8-sig", errors="replace"))
        if not values:
            raise uploads.UploadRejected("process.csv has no values.")
    except (uploads.UploadRejected, ProcessCsvError) as exc:
        raise HTTPException(422, f"process.csv: {exc}") from None
    path = uploads.process_path(settings.nextcloud_root, run)
    with NextcloudClient(settings) as nc:
        nc.upload(path, raw)  # a run has one process table: a new upload replaces it
    tasks().send_task("stemchub.worker.poll_nextcloud")
    params = sorted({v.parameter for v in values})
    return UploadResult(path=path, run_id=run, message=f"{len(values)} values ({', '.join(params)}) uploaded")


# ------------------------------------------------------------------ sync & jobs


@protected.post("/api/sync", dependencies=[Depends(auth.require_scientist)], response_model=Queued, tags=["system"])
def sync_now():
    t = tasks()
    t.send_task("stemchub.worker.sync_elabftw")
    t.send_task("stemchub.worker.poll_nextcloud")
    return Queued(queued=["sync_elabftw", "poll_nextcloud"])


@public.post("/api/hooks/nextcloud", response_model=Queued, tags=["system"])
def nextcloud_webhook(token: str = Query(""), x_webhook_token: str = Header(""), settings: Settings = Depends(get_settings)):
    """Target for Nextcloud's Webhook Listeners app (NodeCreatedEvent). Only a trigger: the body is ignored,
    the poll then reads the actual state from Nextcloud (so a malformed or forged payload can't inject data).
    Needs WEBHOOK_TOKEN as ?token=… or X-Webhook-Token header; disabled when WEBHOOK_TOKEN is empty."""
    given = token or x_webhook_token
    if not settings.webhook_token or not hmac.compare_digest(given.encode(), settings.webhook_token.encode()):
        raise HTTPException(403, "invalid webhook token")
    tasks().send_task("stemchub.worker.poll_nextcloud")
    return Queued(queued=["poll_nextcloud"])


@protected.get("/api/jobs", response_model=list[JobOut], tags=["system"])
def list_jobs(limit: int = Query(30, le=200), session: Session = Depends(get_session)):
    return session.scalars(select(Job).order_by(Job.id.desc()).limit(limit)).all()


@protected.get("/api/links", tags=["system"])
def links(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "omero": settings.omero_web_public_url,
        "elabftw": settings.elab_public_url,
        "nextcloud_folder": settings.nextcloud_root,
    }


app.include_router(auth_routes.router)
app.include_router(public)
app.include_router(protected)


@app.exception_handler(httpx.HTTPError)
async def _http_error(_request, exc: httpx.HTTPError):
    return Response(f"upstream service error: {exc}", status_code=502)

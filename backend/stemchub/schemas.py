"""API response models — they also define the OpenAPI spec the frontend reads (/api/openapi.json)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ServiceStatus(BaseModel):
    name: str
    ok: bool
    detail: str


class Health(BaseModel):
    ok: bool
    services: list[ServiceStatus]


class RunOut(ORM):
    id: str
    title: str | None
    cell_line: str | None
    protocol: str | None
    status: str | None
    elab_id: int | None
    elab_url: str | None = None
    image_count: int = 0
    analyzed_count: int = 0
    days: list[int] = []


class MeasurementOut(ORM):
    day: int
    parameter: str
    value: float
    unit: str | None


class ResultOut(ORM):
    nuclei_count: int
    dead_count: int
    dead_fraction: float
    mean_nucleus_area_um2: float | None
    aggregate_area_um2: float | None
    segmenter: str
    ethd_threshold: float | None
    analyzed_at: datetime


class ImageOut(ORM):
    id: int
    run_id: str
    day: int
    filename: str
    nextcloud_path: str
    omero_image_id: int | None
    omero_url: str | None = None
    size_x: int | None
    size_y: int | None
    size_z: int | None
    channels: list[str] | None
    pixel_size_um: float | None
    status: str
    error: str | None
    result: ResultOut | None


class NucleusOut(ORM):
    label: int
    area_um2: float
    centroid_x: float
    centroid_y: float
    hoechst_mean: float
    ethd_mean: float
    dead: bool


class SummaryRow(BaseModel):
    """One run + day: image results joined with that day's process values — the 'combined view'."""

    run_id: str
    day: int
    images: int
    nuclei: int
    dead_fraction: float | None
    mean_nucleus_area_um2: float | None
    process: dict[str, float]


class JobOut(ORM):
    id: int
    kind: str
    status: str
    message: str | None
    created_at: datetime
    finished_at: datetime | None


class Queued(BaseModel):
    queued: list[str]


class UploadResult(BaseModel):
    path: str
    run_id: str
    day: int | None = None
    message: str


class UserOut(ORM):
    id: int
    username: str
    role: str
    active: bool
    last_login: datetime | None

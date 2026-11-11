"""Database tables. Everything is keyed by run + day — the shared key between OMERO, eLabFTW and Nextcloud."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stemchub.db import Base


def now() -> datetime:
    return datetime.now(UTC)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "U3"
    title: Mapped[str | None] = mapped_column(String(300))
    cell_line: Mapped[str | None] = mapped_column(String(200))
    protocol: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str | None] = mapped_column(String(100))
    elab_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    measurements: Mapped[list["Measurement"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    images: Mapped[list["Image"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Measurement(Base):
    """One process value, e.g. pH on day 5 of run U3."""

    __tablename__ = "measurements"
    __table_args__ = (UniqueConstraint("run_id", "day", "parameter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    parameter: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str | None] = mapped_column(String(500))

    run: Mapped[Run] = relationship(back_populates="measurements")


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(300))
    nextcloud_path: Mapped[str] = mapped_column(String(1000), unique=True)
    nextcloud_etag: Mapped[str | None] = mapped_column(String(200))
    omero_image_id: Mapped[int | None] = mapped_column(Integer)
    omero_import_etag: Mapped[str | None] = mapped_column(String(200))  # file version that was imported
    size_x: Mapped[int | None] = mapped_column(Integer)
    size_y: Mapped[int | None] = mapped_column(Integer)
    size_z: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[list | None] = mapped_column(JSON)
    pixel_size_um: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="new")  # new, queued, importing, analyzing, done, error
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    run: Mapped[Run] = relationship(back_populates="images")
    result: Mapped["ImageResult | None"] = relationship(back_populates="image", cascade="all, delete-orphan")
    nuclei: Mapped[list["Nucleus"]] = relationship(back_populates="image", cascade="all, delete-orphan")


class ImageResult(Base):
    """Summary of the live/dead analysis of one image."""

    __tablename__ = "image_results"

    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    nuclei_count: Mapped[int] = mapped_column(Integer)
    dead_count: Mapped[int] = mapped_column(Integer)
    dead_fraction: Mapped[float] = mapped_column(Float)
    mean_nucleus_area_um2: Mapped[float | None] = mapped_column(Float)
    aggregate_area_um2: Mapped[float | None] = mapped_column(Float)
    segmenter: Mapped[str] = mapped_column(String(50))
    ethd_threshold: Mapped[float | None] = mapped_column(Float)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    image: Mapped[Image] = relationship(back_populates="result")


class Nucleus(Base):
    __tablename__ = "nuclei"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    label: Mapped[int] = mapped_column(Integer)
    area_um2: Mapped[float] = mapped_column(Float)
    centroid_x: Mapped[float] = mapped_column(Float)
    centroid_y: Mapped[float] = mapped_column(Float)
    hoechst_mean: Mapped[float] = mapped_column(Float)
    ethd_mean: Mapped[float] = mapped_column(Float)
    dead: Mapped[bool] = mapped_column(Boolean)

    image: Mapped[Image] = relationship(back_populates="nuclei")


class SourceFile(Base):
    """Remembers which Nextcloud files (e.g. process.csv) we already read, by ETag."""

    __tablename__ = "source_files"

    path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    etag: Mapped[str | None] = mapped_column(String(200))
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued, running, done, error
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer < scientist < admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthSession(Base):
    """A login. The browser holds a random token in an HttpOnly cookie; we store only its SHA-256."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

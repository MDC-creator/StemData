"""API tests against an in-memory SQLite database (no OMERO / Nextcloud / eLabFTW needed)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from stemchub.api import app
from stemchub.auth import current_user
from stemchub.config import Settings, get_settings
from stemchub.db import Base, get_session
from stemchub.models import Image, ImageResult, Measurement, Run

ADMIN = SimpleNamespace(id=1, username="tester", role="admin", active=True)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.add(Run(id="U3", title="Run U3", cell_line="line A", elab_id=7))
        s.add_all(
            [
                Measurement(run_id="U3", day=5, parameter="pH", value=7.1, unit=None),
                Measurement(run_id="U3", day=5, parameter="glucose", value=2.0, unit="g/L"),
                Measurement(run_id="U3", day=9, parameter="pH", value=7.0, unit=None),
            ]
        )
        s.add_all(
            [
                Image(
                    id=1,
                    run_id="U3",
                    day=5,
                    filename="a.czi",
                    nextcloud_path="INDUZELL/U3/day05/a.czi",
                    omero_image_id=11,
                    status="done",
                ),
                Image(
                    id=2,
                    run_id="U3",
                    day=5,
                    filename="b.czi",
                    nextcloud_path="INDUZELL/U3/day05/b.czi",
                    omero_image_id=12,
                    status="done",
                ),
                Image(id=3, run_id="U3", day=9, filename="c.czi", nextcloud_path="INDUZELL/U3/day09/c.czi", status="new"),
            ]
        )
        s.add_all(
            [
                ImageResult(
                    image_id=1, nuclei_count=100, dead_count=10, dead_fraction=0.1, mean_nucleus_area_um2=50, segmenter="t"
                ),
                ImageResult(
                    image_id=2, nuclei_count=50, dead_count=20, dead_fraction=0.4, mean_nucleus_area_um2=70, segmenter="t"
                ),
            ]
        )
        s.commit()

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[current_user] = lambda: ADMIN  # login is tested in test_auth.py
    yield TestClient(app, headers={"X-Requested-With": "stemchub"})
    app.dependency_overrides.clear()


def test_list_runs(client):
    [run] = client.get("/api/runs").json()
    assert run["id"] == "U3" and run["image_count"] == 3 and run["analyzed_count"] == 2
    assert run["days"] == [5, 9]
    assert run["elab_url"].endswith("experiments.php?mode=view&id=7")


def test_run_is_case_insensitive_and_404(client):
    assert client.get("/api/runs/u3").status_code == 200
    assert client.get("/api/runs/U99").status_code == 404


def test_measurements(client):
    rows = client.get("/api/runs/U3/measurements").json()
    assert {(r["parameter"], r["day"]) for r in rows} == {("pH", 5), ("pH", 9), ("glucose", 5)}


def test_images_include_results_and_omero_links(client):
    images = client.get("/api/runs/U3/images").json()
    assert [i["id"] for i in images] == [1, 2, 3]
    assert images[0]["result"]["nuclei_count"] == 100
    assert images[0]["omero_url"].endswith("/webclient/?show=image-11")
    assert images[2]["result"] is None and images[2]["omero_url"] is None


def test_summary_pools_images_of_the_same_day_and_joins_process_values(client):
    rows = {(r["run_id"], r["day"]): r for r in client.get("/api/summary").json()}
    day5 = rows[("U3", 5)]
    assert day5["images"] == 2 and day5["nuclei"] == 150
    assert day5["dead_fraction"] == pytest.approx(30 / 150)  # pooled over nuclei, not averaged per image
    assert day5["process"] == {"pH": 7.1, "glucose": 2.0}
    assert rows[("U3", 9)]["dead_fraction"] is None  # image not analysed yet


def test_thumbnail_of_image_not_in_omero_is_409(client):
    assert client.get("/api/images/3/thumbnail").status_code == 409


def test_webhook_accepts_any_body_and_only_triggers_a_poll(client, monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(webhook_token="s3cret")
    sent = []

    class FakeCelery:
        def send_task(self, name, **kw):
            sent.append(name)

    monkeypatch.setattr("stemchub.api.tasks", lambda: FakeCelery())
    for body in (b'{"event": {"class": "OCP\\Files\\Events\\Node\\NodeCreatedEvent"}}', b"not json", b""):
        r = client.post("/api/hooks/nextcloud?token=s3cret", content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 200
    assert sent == ["stemchub.worker.poll_nextcloud"] * 3


def test_webhook_needs_the_token(client, monkeypatch):
    monkeypatch.setattr("stemchub.api.tasks", lambda: pytest.fail("must not queue anything"))
    app.dependency_overrides[get_settings] = lambda: Settings(webhook_token="s3cret")
    assert client.post("/api/hooks/nextcloud").status_code == 403
    assert client.post("/api/hooks/nextcloud?token=wrong").status_code == 403
    app.dependency_overrides[get_settings] = lambda: Settings(webhook_token="")  # not configured = disabled
    assert client.post("/api/hooks/nextcloud?token=").status_code == 403

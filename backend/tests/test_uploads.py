import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from stemchub import uploads
from stemchub.api import app
from stemchub.auth import current_user
from stemchub.naming import parse_image_path

SCIENTIST = SimpleNamespace(id=2, username="sci", role="scientist", active=True)
CZI = uploads.CZI_MAGIC + b"\x00" * 100  # enough of a CZI for the header check


# ---------------------------------------------------------------- the rules


@pytest.mark.parametrize("day", [-5, -2, 0, 5, 10, 60])
def test_every_path_the_uploader_builds_is_read_back_by_the_sync(day):
    path = uploads.image_path("INDUZELL", "U7", day, "agg 01.czi")
    ref = parse_image_path(path, "INDUZELL")
    assert (ref.run_id, ref.day, ref.filename) == ("U7", day, "agg 01.czi")


def test_paths_look_as_documented():
    assert uploads.image_path("INDUZELL", "U3", 5, "a.czi") == "INDUZELL/U3/day05/a.czi"
    assert uploads.image_path("INDUZELL", "U3", -2, "a.czi") == "INDUZELL/U3/day-02/a.czi"


@pytest.mark.parametrize("bad", ["", " ", "U 3", "../U3", "U3/day05", "-U3", "x" * 65])
def test_bad_run_ids_are_rejected(bad):
    with pytest.raises(uploads.UploadRejected):
        uploads.check_run_id(bad)


def test_run_id_is_normalised():
    assert uploads.check_run_id(" u3 ") == "U3"


@pytest.mark.parametrize("day", [-6, 61])
def test_day_out_of_range(day):
    with pytest.raises(uploads.UploadRejected, match="between"):
        uploads.check_day(day)


def test_browser_paths_are_stripped_to_the_file_name():
    assert uploads.check_image_name("C:\\Users\\lab\\Desktop\\New-05.czi") == "New-05.czi"
    assert uploads.check_image_name("../../etc/New-05.czi") == "New-05.czi"


@pytest.mark.parametrize("bad, why", [("image.tif", "not a .czi"), ("bad;name.czi", "may only contain"), (".czi", "may only")])
def test_bad_file_names(bad, why):
    with pytest.raises(uploads.UploadRejected, match=why):
        uploads.check_image_name(bad)


def test_czi_header_check():
    uploads.check_czi_header(CZI[:10], "a.czi")
    with pytest.raises(uploads.UploadRejected, match="not a Zeiss CZI"):
        uploads.check_czi_header(b"\x89PNG\r\n\x1a\n..", "a.czi")


# ---------------------------------------------------------------- the endpoints (Nextcloud and the queue faked)


class FakeNextcloud:
    files: dict[str, bytes] = {}

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def exists(self, path):
        return path in self.files

    def upload(self, path, data):
        self.files[path] = data if isinstance(data, bytes) else data.read()


@pytest.fixture
def client(monkeypatch):
    FakeNextcloud.files = {}
    sent = []

    class FakeCelery:
        def send_task(self, name, **kw):
            sent.append(name)

    monkeypatch.setattr("stemchub.api.NextcloudClient", FakeNextcloud)
    monkeypatch.setattr("stemchub.api.tasks", lambda: FakeCelery())
    app.dependency_overrides[current_user] = lambda: SCIENTIST
    c = TestClient(app, headers={"X-Requested-With": "stemchub"})
    c.sent = sent
    yield c
    app.dependency_overrides.clear()


def post_image(client, run="u5", day="4", name="agg-01.czi", content=CZI, replace=None):
    data = {"run_id": run, "day": day} | ({"replace": replace} if replace else {})
    return client.post("/api/uploads/image", data=data, files={"file": (name, io.BytesIO(content), "application/octet-stream")})


def test_image_upload_goes_to_the_rule_path_and_triggers_the_import(client):
    r = post_image(client)
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "INDUZELL/U5/day04/agg-01.czi"
    assert FakeNextcloud.files["INDUZELL/U5/day04/agg-01.czi"] == CZI  # whole file, header included
    assert client.sent == ["stemchub.worker.poll_nextcloud"]


def test_existing_file_is_not_overwritten_unless_asked(client):
    assert post_image(client).status_code == 200
    r = post_image(client, content=CZI + b"v2")
    assert r.status_code == 409 and "replace" in r.json()["detail"]
    assert post_image(client, content=CZI + b"v2", replace="true").status_code == 200
    assert FakeNextcloud.files["INDUZELL/U5/day04/agg-01.czi"].endswith(b"v2")


@pytest.mark.parametrize(
    "kw, why",
    [
        ({"content": b"%PDF-1.7 not an image"}, "not a Zeiss CZI"),
        ({"name": "agg.tif"}, "not a .czi"),
        ({"run": "U 5"}, "Run must be"),
        ({"day": "99"}, "between"),
    ],
)
def test_rejected_uploads_never_reach_nextcloud(client, kw, why):
    r = post_image(client, **kw)
    assert r.status_code == 422 and why in r.json()["detail"]
    assert FakeNextcloud.files == {} and client.sent == []


def test_process_csv_is_checked_before_upload(client):
    bad = b"day,parameter,value\n1,pH,seven\n"
    r = client.post("/api/uploads/process", data={"run_id": "U5"}, files={"file": ("p.csv", io.BytesIO(bad), "text/csv")})
    assert r.status_code == 422 and "line 2" in r.json()["detail"]
    assert FakeNextcloud.files == {}

    good = b"day,parameter,value,unit\n1,pH,7.2,\n1,glucose,3.1,g/L\n"
    r = client.post("/api/uploads/process", data={"run_id": "u5"}, files={"file": ("p.csv", io.BytesIO(good), "text/csv")})
    assert r.status_code == 200 and "2 values" in r.json()["message"]
    assert FakeNextcloud.files["INDUZELL/U5/process.csv"] == good

"""eLabFTW through its REST API v2 (doc.elabftw.net/api.html).

Convention: an experiment belongs to a run if it has an extra field "run_id" (template "INDUZELL run").
Extra fields live in the entry's `metadata` JSON under "extra_fields" (doc.elabftw.net/metadata.html).
"""

import json
from dataclasses import dataclass

import httpx

from stemchub.config import Settings


@dataclass(frozen=True)
class ElabRun:
    run_id: str
    elab_id: int
    title: str
    cell_line: str | None
    protocol: str | None
    status: str | None


class ElabError(RuntimeError):
    pass


def extra_fields(entry: dict) -> dict:
    raw = entry.get("metadata")
    if not raw:
        return {}
    meta = json.loads(raw) if isinstance(raw, str) else raw
    return (meta or {}).get("extra_fields", {}) or {}


def field_value(fields: dict, *names: str) -> str | None:
    lowered = {k.lower(): v for k, v in fields.items()}
    for name in names:
        value = (lowered.get(name.lower()) or {}).get("value")
        if value not in (None, ""):
            return str(value)
    return None


def to_run(entry: dict) -> ElabRun | None:
    fields = extra_fields(entry)
    run_id = field_value(fields, "run_id", "run id")
    if not run_id:
        return None
    return ElabRun(
        run_id=run_id.strip().upper(),
        elab_id=int(entry["id"]),
        title=entry.get("title") or "",
        cell_line=field_value(fields, "cell_line", "cell line"),
        protocol=field_value(fields, "protocol"),
        status=entry.get("status_title"),
    )


class ElabClient:
    def __init__(self, settings: Settings, timeout: float = 30.0):
        self.public_url = settings.elab_public_url.rstrip("/")
        self.client = httpx.Client(
            base_url=settings.elab_url.rstrip("/") + "/api/v2",
            headers={"Authorization": settings.elab_api_key},
            verify=settings.elab_verify_tls,
            timeout=timeout,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code >= 400:
            raise ElabError(f"{what} failed: HTTP {r.status_code} {r.text[:200]}")
        return r

    def experiment_url(self, elab_id: int) -> str:
        return f"{self.public_url}/experiments.php?mode=view&id={elab_id}"

    def me(self) -> dict:
        return self._check(self.client.get("/users/me"), "users/me").json()

    def list_experiments(self, limit: int = 500) -> list[dict]:
        return self._check(self.client.get("/experiments", params={"limit": limit}), "list experiments").json()

    def get_experiment(self, elab_id: int) -> dict:
        return self._check(self.client.get(f"/experiments/{elab_id}"), f"experiment {elab_id}").json()

    def runs(self) -> list[ElabRun]:
        # the list endpoint may omit metadata, so read each entry that could be a run
        result = []
        for entry in self.list_experiments():
            if "metadata" not in entry:
                entry = self.get_experiment(int(entry["id"]))
            run = to_run(entry)
            if run:
                result.append(run)
        return result

    def create_experiment(self, title: str, body: str = "", fields: dict | None = None, tags: list[str] | None = None) -> int:
        r = self._check(self.client.post("/experiments", json={"title": title}), "create experiment")
        elab_id = int(r.headers["location"].rstrip("/").split("/")[-1])
        patch: dict = {"body": body}
        if fields is not None:
            patch["metadata"] = json.dumps({"extra_fields": fields})
        self._check(self.client.patch(f"/experiments/{elab_id}", json=patch), "update experiment")
        for tag in tags or []:
            self._check(self.client.post(f"/experiments/{elab_id}/tags", json={"tag": tag}), "add tag")
        return elab_id

    def set_extra_fields(self, elab_id: int, updates: dict[str, dict]) -> None:
        """Merge extra fields into the entry, keeping the existing ones."""
        entry = self.get_experiment(elab_id)
        raw = entry.get("metadata")
        meta = (json.loads(raw) if isinstance(raw, str) else raw) or {}
        meta.setdefault("extra_fields", {}).update(updates)
        self._check(
            self.client.patch(f"/experiments/{elab_id}", json={"metadata": json.dumps(meta)}),
            f"update metadata {elab_id}",
        )

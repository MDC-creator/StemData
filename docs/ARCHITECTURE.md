# Architecture

StemCDataHub connects three existing systems and adds what none of them does: automatic image
analysis and one view that puts images, process data and results side by side.

```
                         ┌───────── lab servers (later) / infra/dev-stack (local) ─────────┐
 lab ── .czi, CSV ──▶    │  Nextcloud (files)     OMERO (images)      eLabFTW (run records) │
                         └──────┬───────────────────────▲─────────────────────▲────────────┘
                     WebDAV ↓↑  │          omero-py + importer ↕         REST v2 ↕
                         ┌──────┴─────────────── our app (compose.yaml) ──────┴────────────┐
                         │  worker (Celery)  ◀── redis ──  api (FastAPI)  ◀── web (React)  │
                         │        └──────────── PostgreSQL ◀─────┘                         │
                         └─────────────────────────────────────────────────────────────────┘
```

## Principles

1. **We don't replace the platforms, we connect them.** Raw images stay in OMERO, run records in
   eLabFTW, files in Nextcloud. Our database holds links (IDs, paths) and *derived* data only.
2. **Only official interfaces.** WebDAV for Nextcloud, REST API v2 for eLabFTW, omero-py and the
   standard importer for OMERO. Nothing is installed inside the platforms — so they can be updated
   independently, and moving from the local stack to the lab servers is a configuration change (`.env`).
3. **One shared key: run + day.** Every image and every process value carries `run_id` and `day`.
4. **Slow work runs in the background.** The API answers in milliseconds; imports and Cellpose run
   in the worker.

## The shared-key rule

| Where | Rule |
|---|---|
| Nextcloud | `INDUZELL/<run_id>/day<NN>/<file>.czi` (days may be negative: `day-02`), process data in `INDUZELL/<run_id>/process.csv` |
| eLabFTW | experiment with the extra field `run_id` (also read: `cell_line`, `protocol`) |
| OMERO | project `INDUZELL` › dataset `<run_id>`; every image gets key-values `run_id`, `day`, `source` (namespace `stemcdatahub.induzell`) |

Files that don't follow the rule are reported as *skipped* by the sync (see Activity page).

## Data flow

0. **Uploader** (`POST /api/uploads/image`, `/api/uploads/process`, Upload page): the user picks run + day,
   the path is built from the naming rule (so it can't be wrong), the file is checked (CZI magic bytes,
   CSV parsed) and streamed to Nextcloud, then a poll is triggered. Files saved directly into Nextcloud
   follow the same rule and are picked up by the poll.
1. **poll_nextcloud** (every 60 s, or immediately via `POST /api/hooks/nextcloud`): walks the folder
   with WebDAV `PROPFIND`, registers new `.czi` files as images, (re)reads changed `process.csv`
   files (compared by ETag) into `measurements`.
2. **process_image** (one per new image): download via WebDAV → `omero import` into the run's
   dataset → key-values → read all planes with omero-py → live/dead analysis → results into our DB,
   one mask ROI per nucleus into OMERO, outline overlay PNG into the cache.
3. **sync_elabftw** (every 120 s): experiments with `run_id` → `runs` (title, cell line, protocol).
4. **writeback** (after each analysis): `INDUZELL/exports/<run>_results.csv` into Nextcloud, and
   link + summary as extra fields into the run's eLabFTW entry.

Every task that did something is recorded in the `jobs` table (Activity page); routine checks that
found nothing are not recorded, and a file breaking the naming rule is reported once.

## Analysis (backend/stemchub/analysis.py)

Two-channel confocal stacks: Hoechst 33342 (all nuclei) and EthD (dead cells).

1. maximum-intensity projection over z per channel
2. nuclei segmentation in Hoechst: Cellpose 3 `nuclei` model (CPU), diameter from
   `NUCLEUS_DIAMETER_UM` / pixel size; `SEGMENTER=classic` uses Otsu + watershed instead
3. per nucleus: area, centroid, mean Hoechst and EthD intensity
4. **dead** = mean EthD at least `ETHD_MIN_Z` (6) robust SDs above the EthD background (pixels outside
   all nuclei) **and** at least `ETHD_MIN_RATIO` (1.5) × brighter than it
5. **aggregate area** = nuclei joined across the gaps between them (closing with one nucleus diameter),
   inside filled — a hollow aggregate counts with its full outline

Why not a global Otsu threshold for "dead": on the sample data the EthD channel is pure noise (brightest
nucleus 1.13 × background). Otsu still splits noise in two and called ~60 % of nuclei dead. A regression
test (`test_no_ethd_signal_means_no_dead_cells`) keeps this from coming back.

Limitations: the max projection merges nuclei that overlap in z, so counts in thick aggregates are too
low (3D segmentation is a next step); strong Hoechst→EthD crosstalk (> ~1.5 × background) would be
counted as dead and needs a crosstalk correction or a control sample to calibrate the thresholds.

## Components

| Part | Tech | Code |
|---|---|---|
| API | FastAPI, Pydantic, SQLAlchemy 2 | `backend/stemchub/api.py`, `schemas.py`, `models.py` |
| Worker | Celery + Redis, Cellpose 3, omero-py, Java (importer) | `backend/stemchub/worker.py`, `pipeline.py`, `analysis.py` |
| Connectors | httpx (WebDAV, REST), omero-py | `backend/stemchub/connectors/` |
| Database | PostgreSQL 16 (tables created on start; Alembic migrations are a next step) | `models.py` |
| Web UI | React 18, TypeScript, Vite, TanStack Query, Plotly | `frontend/src/` |
| API types | generated from the OpenAPI spec (`npm run gen:api`) | `frontend/src/api/schema.d.ts` |

## API

Interactive documentation: http://localhost:8000/api/docs (or http://localhost:8090/api/docs through the web UI).

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | reachability of DB, queue, OMERO, Nextcloud, eLabFTW |
| `GET /api/runs`, `/api/runs/{id}` | runs with image counts and eLabFTW link |
| `GET /api/runs/{id}/measurements` | process values |
| `GET /api/runs/{id}/images` | images with analysis results and OMERO link |
| `GET /api/summary` | per run and day: image results joined with process values |
| `GET /api/images/{id}/thumbnail`, `/preview`, `/mask` | max projection rendered by OMERO once, then cached |
| `GET /api/images/{id}/nuclei` | per-nucleus measurements |
| `POST /api/uploads/image`, `/api/uploads/process` | upload under the naming rule (409 if the file exists, unless `replace`) |
| `POST /api/sync`, `/api/images/{id}/reprocess`, `/api/hooks/nextcloud` | trigger work |
| `GET /api/jobs` | recent background tasks |

## Moving to the lab servers

Change `.env` only: `OMERO_HOST`/`OMERO_USER`/`OMERO_PASSWORD` (service account), `NEXTCLOUD_URL`/
`NEXTCLOUD_USER`/`NEXTCLOUD_PASSWORD` (app password), `ELAB_URL`/`ELAB_API_KEY`, `ELAB_VERIFY_TLS=true`,
public URLs. Remove the `lab` network from `compose.yaml` when the services are not local.

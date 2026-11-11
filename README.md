# StemCDataHub

A web platform that connects the data systems of a stem-cell lab and analyses microscope images
automatically. A new image saved to the lab's file share is imported into the image database,
segmented with a neural network, and shown next to the process data of the same culture run.

Built as a university project at Hochschule Hannover together with a stem-cell research lab.
Research data is **not** part of this repository.

![CI](https://github.com/MDC-creator/StemData/actions/workflows/ci.yml/badge.svg)

## What it does

- **Connects three existing platforms through their official APIs** instead of replacing them:
  Nextcloud (files, WebDAV), OMERO (microscopy images, omero-py) and eLabFTW (lab notebook, REST API v2).
- **Watches for new data**: polling every 60 s plus a webhook trigger; files that break the naming rule are reported.
- **Analyses every image in the background**: nuclei segmentation with Cellpose 3, live/dead classification
  with a robust background threshold, aggregate area; masks are written back to OMERO as ROIs.
- **Writes results back**: results CSV to Nextcloud, link and summary to the eLabFTW entry.
- **One web UI** for runs, process curves, image viewer with mask overlay, run comparison, uploads and activity log.
- **Login with roles** (viewer, scientist, admin), server-side sessions in an HttpOnly cookie.

## Architecture

```
 lab ── .czi, CSV ──▶  Nextcloud (files)     OMERO (images)      eLabFTW (run records)
                            WebDAV ↕         omero-py + importer ↕       REST v2 ↕
                     ┌─────────────────────────── this app ────────────────────────────┐
                     │  worker (Celery)  ◀── Redis ──  api (FastAPI)  ◀── web (React)  │
                     │        └──────────────── PostgreSQL ◀──────┘                    │
                     └─────────────────────────────────────────────────────────────────┘
```

Design decisions, data flow and the analysis method: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech stack

| Area | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, PostgreSQL 16 |
| Background jobs | Celery, Redis |
| Image analysis | Cellpose 3, scikit-image, SciPy, NumPy |
| Frontend | React 18, TypeScript, Vite, TanStack Query, Plotly; API types generated from OpenAPI |
| Operations | Docker Compose (app + complete local lab stack), nginx |
| Quality | pytest (unit, regression and API tests), ruff, CI with GitHub Actions |

## Run it locally

Requirements: Docker Desktop (at least 8 GB memory), Git, about 15 GB free disk. On Windows use Git Bash.

```bash
git clone https://github.com/MDC-creator/StemData.git
cd StemData
./scripts/setup.sh --simple-logins
```

The first run takes 15–20 minutes, because it also starts a complete local lab stack
(OMERO, Nextcloud, eLabFTW). Without `--simple-logins`, random passwords are created and printed at the end.

| Service | URL | User | Password |
|---|---|---|---|
| StemCDataHub | http://localhost:8090 | `root` | `root` |
| OMERO | http://localhost:4080 | `root` | `root` |
| Nextcloud | http://localhost:8081 | `root` | `root` |
| eLabFTW | https://localhost:8443 | `root@root.local` | `root` |

These logins exist only with `--simple-logins` and are meant for local testing; all ports are bound to localhost.
eLabFTW uses a self-signed certificate, so accept the browser warning.

## Add data

Use the **Upload** page (choose run and day), or save files in Nextcloud as:

- images: `INDUZELL/<run>/day<NN>/<name>.czi` (e.g. `INDUZELL/U3/day05/a.czi`)
- process values: `INDUZELL/<run>/process.csv` with the columns `day,parameter,value,unit`

## Daily use

```bash
./scripts/setup.sh --simple-logins                                          # start
docker compose stop && docker compose -f infra/dev-stack/compose.yaml stop  # stop
docker compose logs --tail 50 worker                                        # what the worker did
git pull && docker compose up -d --build                                    # update
```

## Develop

```bash
docker compose run --rm api pytest      # backend tests
cd frontend && npm install && npm run dev
```

## Author

Mohamed Dhia Chamam · [github.com/MDC-creator](https://github.com/MDC-creator)

# Status and roadmap

## Done (verified on the local stack)

- [x] Dev stack: OMERO 5.6, OMERO.web 5.33, Nextcloud 34, eLabFTW 6 (+ dev account with API key)
- [x] App: FastAPI + PostgreSQL + Redis + Celery worker + React UI, all in Docker
- [x] `/api/health` checks all five dependencies
- [x] Nextcloud polling (60 s) + webhook trigger; naming-rule violations reported once
- [x] Import into OMERO (project per study, dataset per run), key-values, idempotent re-import
- [x] Live/dead analysis with Cellpose 3 (CPU); masks as ROIs in OMERO; outline overlay in the UI
- [x] Write-back: results CSV to Nextcloud, link + summary to eLabFTW
- [x] UI: runs, run detail (curves + images + viewer + charts + day table), compare, activity
- [x] Uploader: pick run + day, files checked (CZI header, CSV) and saved under the naming rule, import starts at once
- [x] Login with server-side sessions and three roles (viewer, scientist, admin)
- [x] Tests for naming, CSV, analysis (incl. regression tests), API, auth and uploads; ruff; CI on every push

## Next

- [ ] Validate the analysis on samples with dead cells to calibrate the `ETHD_MIN_*` thresholds
- [ ] Brightfield analysis (aggregate size and shape per day)
- [ ] Single sign-on (OIDC)
- [ ] Alembic migrations instead of create-on-start
- [ ] Production deployment (service accounts, TLS, backups)
- [ ] 3D segmentation for thick aggregates; optional OMERO.web plugin tab

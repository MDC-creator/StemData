# One image definition, two targets:
#   api    — FastAPI (small)
#   worker — Celery + Cellpose (CPU) + Java for the OMERO importer (large)

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# omero-py needs ZeroC Ice 3.6; Glencoe Software publishes prebuilt wheels (building it takes ~15 min)
ARG ICE_WHEEL=https://github.com/glencoesoftware/zeroc-ice-py-linux-x86_64/releases/download/20240202/zeroc_ice-3.6.5-cp312-cp312-manylinux_2_28_x86_64.whl
RUN pip install "$ICE_WHEEL"

COPY requirements/api.txt requirements/dev.txt requirements/
RUN pip install -r requirements/api.txt -r requirements/dev.txt

RUN useradd --create-home --uid 1000 app && mkdir -p /cache && chown app:app /cache

# ---------------------------------------------------------------- api
FROM base AS api
COPY pyproject.toml ./
COPY stemchub/ stemchub/
COPY tests/ tests/
USER app
EXPOSE 8000
CMD ["uvicorn", "stemchub.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

# ---------------------------------------------------------------- worker
FROM base AS worker
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements/worker.txt requirements/
RUN pip install -r requirements/worker.txt

USER app
# bake in the OMERO importer jars and the Cellpose nuclei model, so the worker works offline
RUN omero import --fetch-jars latest \
 && python -c "from cellpose import models; models.Cellpose(gpu=False, model_type='nuclei')"

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app stemchub/ stemchub/
CMD ["celery", "-A", "stemchub.worker", "worker", "-B", "--concurrency=1", "--loglevel=INFO", "--schedule=/cache/celerybeat-schedule"]

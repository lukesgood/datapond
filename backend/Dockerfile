# Backend Dockerfile for DataPond — build from REPO ROOT:
#   docker build -f backend/Dockerfile --target enterprise .
#   docker build -f backend/Dockerfile --target community .
# enterprise = community + /ee (commercially licensed, see ee/LICENSE).
FROM python:3.11.15-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# ── Community edition: Apache-2.0 code only ────────────────────────────────────
FROM base AS community
RUN useradd -m -u 1000 datapond && chown -R datapond:datapond /app
USER datapond
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Enterprise edition: + /ee (DataPond Commercial License) ────────────────────
FROM base AS enterprise
COPY ee/backend/ee /app/ee
RUN useradd -m -u 1000 datapond && chown -R datapond:datapond /app
USER datapond
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

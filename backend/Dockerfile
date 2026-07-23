FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the ReconOS securities seed dataset (deterministic, byte-identical)
# into the image so the app boots demo-ready. A failure here should fail the
# build loudly — the seed generator self-checks every demo scenario.
RUN python -m app.seed.generator --out ./data

EXPOSE 8000

# Cloud Run injects PORT (normally 8080).  Retain 8000 as the local Docker
# default so docker-compose and the documented development URL keep working.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]

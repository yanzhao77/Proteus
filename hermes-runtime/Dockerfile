FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN groupadd --system hermes && useradd --system --gid hermes --home-dir /nonexistent --shell /usr/sbin/nologin hermes

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /app/requirements.txt

COPY src /app/src
COPY migrations /app/migrations

USER hermes

EXPOSE 8080

CMD ["uvicorn", "hermes_runtime.api_main:app", "--host", "0.0.0.0", "--port", "8080"]

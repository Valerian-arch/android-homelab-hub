FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HUB_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user. The /data volume must be writable by UID 10001.
RUN useradd --system --uid 10001 --no-create-home hub \
    && mkdir -p /data && chown hub /data && chmod 700 /data
USER hub

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

# umask 077: every file the Hub creates (database, key) is readable only by the hub user.
CMD ["sh", "-c", "umask 077 && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080"]

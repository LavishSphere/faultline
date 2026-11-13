# FAULTLINE API image (CPU only). Built by deploy/docker-compose.yml with context ../services/api.
# Runs as a fixed non-root uid; the container filesystem is read-only except /app/var (volume) and /tmp (tmpfs).
FROM python:3.12.16-slim

# FAULTLINE_MODE=public is the fail-safe default: an image started without it still runs in public mode.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FAULTLINE_MODE=public

RUN groupadd --system --gid 10001 faultline \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin faultline

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e . \
    && mkdir -p /app/var \
    && chown -R 10001:10001 /app/var

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

# One worker: the in-process rate limiter is per worker (docs/DEPLOY.md). --proxy-headers takes the client IP
# from Caddy's X-Forwarded-For; port 8000 is reachable only from Caddy on the internal `edge` network.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]

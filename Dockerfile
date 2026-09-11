# syntax=docker/dockerfile:1

# ---- build stage: compile wheels into a self-contained venv ----------------
FROM python:3.13-alpine AS builder

# Only needed if a dependency has no musllinux wheel; discarded with this stage.
RUN apk add --no-cache build-base libffi-dev openssl-dev

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY verification_bot ./verification_bot

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir ".[encryption,docker]" \
    && find /opt/venv -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /opt/venv -name '*.dist-info' -type d -exec rm -rf {}/RECORD \; 2>/dev/null || true

# ---- runtime stage --------------------------------------------------------
FROM python:3.13-alpine AS runtime

RUN apk add --no-cache libffi tini \
    && adduser -D -H -u 10001 bot

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY resources ./resources

# Mount point for the log volume; pre-created because the root filesystem is read-only.
RUN mkdir -p /app/logs && chown -R bot:bot /app/logs

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    HEARTBEAT_FILE=/tmp/heartbeat

USER bot

# Considers the bot unhealthy if the gateway heartbeat stops being refreshed.
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,time; p=os.environ['HEARTBEAT_FILE']; sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 150 else 1)"

ENTRYPOINT ["/sbin/tini", "--", "python", "-m", "verification_bot"]

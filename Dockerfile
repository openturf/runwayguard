FROM python:3.11-slim as builder

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL maintainer="andrew@openturf.org" \
      org.opencontainers.image.title="RunwayGuard" \
      org.opencontainers.image.description="Advanced Runway Risk Intelligence for Aviation Safety" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/awade12/runwayguard" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

RUN pip install --upgrade pip wheel && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim as production

RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd -r runwayguard && \
    useradd --no-log-init -r -g runwayguard runwayguard

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --chown=runwayguard:runwayguard . .

RUN rm -rf tests/ docs/example/ .github/ .git* *.md requirements.txt

RUN mkdir -p /app/logs && \
    chown -R runwayguard:runwayguard /app

USER runwayguard

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

# HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
#     CMD curl -f http://localhost:8000/v1/info || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18001", "--workers", "1"]

LABEL aviation.safety.level="production" \
      aviation.compliance.reviewed="2024-01-01" \
      aviation.data.sources="FAA,NOAA" \
      aviation.risk.assessment="advanced" 
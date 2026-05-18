FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r marm && useradd -r -g marm -m marm

COPY --chown=marm:marm . .
RUN pip install --no-cache-dir .

USER marm

ENV MARM_DASHBOARD_HOST=0.0.0.0
ENV MARM_DASHBOARD_PORT=8002

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

CMD ["python", "-m", "marm_dashboard"]

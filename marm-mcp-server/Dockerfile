FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2" && \
    pip install --no-cache-dir --user --ignore-installed -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN groupadd -r marm && useradd -r -g marm marm
RUN mkdir -p /home/marm /home/marm/.marm /home/marm/.cache
RUN chown -R marm:marm /home/marm

COPY --from=builder --chown=marm:marm /root/.local /home/marm/.local

RUN mkdir -p /app/data && chown marm:marm /app/data

COPY --chown=marm:marm . .

USER marm
ENV PATH=/home/marm/.local/bin:$PATH

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

LABEL org.opencontainers.image.title="MARM Universal MCP Server"
LABEL org.opencontainers.image.description="Production-ready Universal MCP Server with advanced AI memory capabilities, semantic search, and professional-grade architecture"
LABEL org.opencontainers.image.version="2.15.1"
LABEL org.opencontainers.image.authors="Ryan Lyell - MARM Systems"
LABEL org.opencontainers.image.url="https://marmsystems.com"
LABEL org.opencontainers.image.source="https://github.com/Lyellr88/MARM-Systems"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL mcp.server="true"
LABEL mcp.name="marm-mcp-server"
LABEL mcp.tools="7"
LABEL io.modelcontextprotocol.server.name="io.github.Lyellr88/marm-mcp-server"

ENV PYTHONPATH=/app
ENV MARM_LOG_LEVEL=INFO
ENV SERVER_HOST=0.0.0.0

ENTRYPOINT ["python", "-m", "marm_mcp_server"]
CMD []

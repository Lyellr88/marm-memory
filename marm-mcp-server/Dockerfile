FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY marm_mcp_server ./marm_mcp_server
COPY marm_graph ./marm_graph
COPY scripts/bundle-concept-model.py ./scripts/bundle-concept-model.py
RUN python scripts/bundle-concept-model.py && \
    pip install --no-cache-dir --upgrade "wheel>=0.46.2" && \
    pip install --no-cache-dir --user ".[docker-image]"

RUN set -eux; \
    VERSION="$(python -c 'from codebase_memory_mcp import _cli; print(_cli._version())')"; \
    OS_NAME="$(python -c 'from codebase_memory_mcp import _cli; print(_cli._os_name())')"; \
    ARCH="$(python -c 'from codebase_memory_mcp import _cli; print(_cli._arch())')"; \
    VARIANT=""; [ "$OS_NAME" = "linux" ] && VARIANT="-portable"; \
    ARCHIVE="codebase-memory-mcp-${OS_NAME}-${ARCH}${VARIANT}.tar.gz"; \
    RELEASE_URL="https://github.com/DeusData/codebase-memory-mcp/releases/download/v${VERSION}"; \
    curl -fsSL "${RELEASE_URL}/${ARCHIVE}" -o "/tmp/${ARCHIVE}"; \
    curl -fsSL "${RELEASE_URL}/checksums.txt" -o /tmp/checksums.txt; \
    (cd /tmp && grep "${ARCHIVE}" checksums.txt | sha256sum -c -); \
    mkdir -p /tmp/extract && tar -xzf "/tmp/${ARCHIVE}" -C /tmp/extract; \
    cp /tmp/extract/codebase-memory-mcp /usr/local/bin/codebase-memory-mcp-bin; \
    chmod +x /usr/local/bin/codebase-memory-mcp-bin; \
    rm -rf "/tmp/${ARCHIVE}" /tmp/checksums.txt /tmp/extract \
 && test -f /usr/local/bin/codebase-memory-mcp-bin

FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r marm && useradd -r -g marm marm
RUN mkdir -p /home/marm /home/marm/.marm /home/marm/.cache
RUN chown -R marm:marm /home/marm

COPY --from=builder --chown=marm:marm /root/.local /home/marm/.local
COPY --from=builder /usr/local/bin/codebase-memory-mcp-bin /usr/local/bin/codebase-memory-mcp-bin

RUN mkdir -p /app/data && chown marm:marm /app/data

COPY --chown=marm:marm . .
COPY --from=builder --chown=marm:marm \
    /app/marm_mcp_server/models /app/marm_mcp_server/models
RUN mkdir -p /licenses \
 && cp /app/LICENSE /licenses/MARM-LICENSE \
 && cp /app/THIRD_PARTY_NOTICES.md /licenses/THIRD_PARTY_NOTICES.md

USER marm
ENV PATH=/home/marm/.local/bin:$PATH

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=5)" || exit 1

LABEL org.opencontainers.image.title="MARM Universal MCP Server"
LABEL org.opencontainers.image.description="Production-ready Universal MCP Server with advanced AI memory capabilities, semantic search, and professional-grade architecture"
LABEL org.opencontainers.image.version="2.47.0"
LABEL org.opencontainers.image.authors="Ryan Lyell - marm-memory"
LABEL org.opencontainers.image.url="https://marmsystems.com"
LABEL org.opencontainers.image.source="https://github.com/Lyellr88/marm-memory"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL mcp.server="true"
LABEL mcp.name="marm-mcp-server"
LABEL mcp.tools="14"
LABEL io.modelcontextprotocol.server.name="io.github.Lyellr88/marm-mcp-server"

ENV PYTHONPATH=/app
ENV MARM_LOG_LEVEL=INFO
ENV SERVER_HOST=0.0.0.0
ENV CBM_BINARY_PATH=/usr/local/bin/codebase-memory-mcp-bin

ENTRYPOINT ["python", "-m", "marm_mcp_server"]
CMD []

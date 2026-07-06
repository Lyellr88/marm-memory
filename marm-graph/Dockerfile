# marm-graph — wraps a pinned codebase-memory-mcp binary, baked at BUILD time.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY marm_graph ./marm_graph

RUN pip install --no-cache-dir .

# Bake the pinned static binary into the image NOW, not at runtime — by
# downloading the release archive ourselves, verifying its SHA256 against
# checksums.txt, and extracting the shipped binary FROM THAT VERIFIED ARCHIVE.
# We do NOT use the PyPI shim's own cached download as the source: the shim's
# checksum check is best-effort (it silently skips verification if the
# checksums.txt fetch fails, see codebase_memory_mcp/_cli.py:_verify_checksum),
# so trusting its cache would let an unverified binary slip into the image even
# though a separate, correctly-verified archive was also downloaded alongside
# it. curl is installed and purged within this single layer so the final image
# never carries it.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && set -eux; \
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
 && apt-get purge -y --auto-remove curl && rm -rf /var/lib/apt/lists/* \
 && test -f /usr/local/bin/codebase-memory-mcp-bin

RUN groupadd -r marm && useradd -r -g marm marm \
 && mkdir -p /home/marm/.marm && chown -R marm:marm /home/marm /app

ENV CBM_BINARY_PATH=/usr/local/bin/codebase-memory-mcp-bin
ENV SERVER_PORT=8003

# Safe by default: binds 127.0.0.1. To expose on a network interface you MUST set
# BOTH  SERVER_HOST=0.0.0.0  AND  MARM_GRAPH_API_KEY=<key>  — the server refuses to
# start on a non-loopback interface without a key.
EXPOSE 8003

USER marm

CMD ["marm-graph"]

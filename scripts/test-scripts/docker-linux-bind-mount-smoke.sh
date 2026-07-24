#!/usr/bin/env bash
# Linux-only Docker smoke test for host UID/GID bind-mount persistence.
set -Eeuo pipefail

readonly image="${MARM_DOCKER_SMOKE_IMAGE:-lyellr88/marm-mcp-server:latest}"
smoke_root="$(mktemp -d)"
readonly smoke_root
readonly container_name="marm-linux-smoke-$$"
api_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
readonly api_key
readonly data_dir="$smoke_root/data"
readonly env_file="$smoke_root/marm.env"
port="$(python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
readonly port

cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  rm -rf "$smoke_root"
}
trap cleanup EXIT

start_container() {
  docker run -d \
    --name "$container_name" \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$data_dir,dst=/home/marm/.marm" \
    --env-file "$env_file" \
    -e SERVER_HOST=0.0.0.0 \
    -e HOME=/home/marm \
    -e XDG_CACHE_HOME=/home/marm/.marm/cache \
    -p "127.0.0.1:$port:8001" \
    "$image" >/dev/null
}

wait_for_health() {
  for _attempt in $(seq 1 30); do
    if curl --fail --silent "http://127.0.0.1:$port/health" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  docker logs "$container_name"
  return 1
}

docker image inspect "$image" >/dev/null 2>&1 || docker pull "$image"
mkdir -p "$data_dir"
printf 'MARM_API_KEY=%s\n' "$api_key" > "$env_file"

start_container
wait_for_health

response="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer $api_key" \
  --header 'Content-Type: application/json' \
  --data '{"content":"Linux Docker mount smoke memory","session_name":"docker-smoke","context_type":"test","metadata":{"source":"linux-smoke"}}' \
  "http://127.0.0.1:$port/internal/memories")"
memory_id="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])' <<< "$response")"
database="$data_dir/marm_memory.db"

test -s "$database"
test "$(stat --format='%u:%g' "$database")" = "$(id -u):$(id -g)"

docker stop "$container_name" >/dev/null
docker rm "$container_name" >/dev/null

start_container
wait_for_health

count="$(python3 - "$database" "$memory_id" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    print(connection.execute("SELECT COUNT(*) FROM memories WHERE id = ?", (sys.argv[2],)).fetchone()[0])
PY
)"
test "$count" = "1"

echo "PASS: Linux Docker bind-mount persistence verified."

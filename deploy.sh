#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }

rand() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 24
  else head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

if [ ! -f .env ]; then
  umask 077
  # Every placeholder gets its own random secret; the stack never starts on a known default.
  while IFS= read -r line || [ -n "$line" ]; do
    while [[ "$line" == *__GENERATE__* ]]; do line="${line/__GENERATE__/$(rand)}"; done
    printf '%s\n' "$line"
  done < .env.example > .env
  echo "Created .env with generated secrets (mode 600). Keys are in .env: API_KEY and API_KEYS."
fi

if grep -Eq '__GENERATE__|^API_KEY=(change-me-now)?$' .env; then
  echo "Refusing to start: .env still contains placeholder or default credentials." >&2
  exit 1
fi

docker compose up -d --build
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
    echo "Parinita GrowthOS is healthy at http://localhost:8080 (bound to ${BIND_ADDR:-127.0.0.1})"
    echo "Next: ./examples/demo.sh   |   acceptance: docs/THREE_DAY_ACCEPTANCE.md"
    exit 0
  fi
  sleep 2
done
echo "GrowthOS did not become healthy. Run: docker compose logs --tail=200" >&2
exit 1

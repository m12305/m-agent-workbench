#!/bin/sh
set -e

echo "============================================"
echo "  m-agent-workbench Backend"
echo "  DB Backend:  ${REPOSITORY_BACKEND:-sqlite}"
echo "  Milvus Host: ${MILVUS_HOST:-unconfigured}"
echo "  Workers:     ${UVICORN_WORKERS:-1}"
echo "============================================"

# ── Detect first run ──
FIRST_RUN="no"
if [ ! -f /app/data/mka.db ]; then
    FIRST_RUN="yes"
fi

# ── Start ──
echo "Starting Uvicorn..."

if [ "$FIRST_RUN" = "yes" ]; then
    echo ""
    echo "============================================"
    echo "  FIRST RUN — create admin account:"
    echo ""
    echo "  docker compose exec backend python -m src.server.bootstrap_admin --name Administrator"
    echo ""
    echo "  Save the API Key — it will not be shown again."
    echo "============================================"
fi

exec uvicorn src.server.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-1}" \
    --log-level "${LOG_LEVEL:-info}"

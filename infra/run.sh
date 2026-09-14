#!/bin/bash
set -euo pipefail
export PYTHONPATH="${LAMBDA_TASK_ROOT}:${PYTHONPATH:-}"
exec python -m uvicorn imhungry.runtime:app_factory --factory --host 0.0.0.0 --port 8000 --no-access-log

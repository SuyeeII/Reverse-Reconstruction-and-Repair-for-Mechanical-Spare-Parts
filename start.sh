#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONPATH="$task_root/src"
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
export LD_LIBRARY_PATH="$task_root/runtime/system/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$task_root/.venv/bin/python" "$task_root/scripts/start_vision.py" "$@"

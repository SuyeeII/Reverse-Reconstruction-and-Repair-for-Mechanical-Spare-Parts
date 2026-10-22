#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
${PYTHON:-python3.12} -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p runs reports evidence runtime
ln -sfn "$(command -v node)" runtime/node
mkdir -p runtime/system/usr/bin
ln -sfn "$(command -v prusa-slicer)" runtime/system/usr/bin/prusa-slicer

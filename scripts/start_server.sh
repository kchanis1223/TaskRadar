#!/usr/bin/env bash
set -euo pipefail

PORT="8501"
ADDRESS="127.0.0.1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="$2"
      shift 2
      ;;
    --address)
      ADDRESS="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

export TASKRADAR_USE_OPENCODE="${TASKRADAR_USE_OPENCODE:-1}"
export TASKRADAR_REQUIRE_OPENCODE="${TASKRADAR_REQUIRE_OPENCODE:-1}"
export TASKRADAR_MODE="${TASKRADAR_MODE:-demo}"

OPENCODE_COMMAND="${TASKRADAR_OPENCODE_COMMAND:-opencode}"
if ! command -v "${OPENCODE_COMMAND}" >/dev/null 2>&1; then
  if [[ ! -x "${OPENCODE_COMMAND}" ]]; then
    echo "opencode command was not found: ${OPENCODE_COMMAND}" >&2
    echo "Set TASKRADAR_OPENCODE_COMMAND in .env or fix PATH." >&2
    exit 1
  fi
fi

PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  echo "Virtual environment is missing. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

exec "${PYTHON}" -m streamlit run app.py \
  --server.address "${ADDRESS}" \
  --server.port "${PORT}" \
  --server.headless true

#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS_DIR="${REPO_ROOT}/reports"
mkdir -p "${REPORTS_DIR}"

RUN_STAMP="$(date +"%Y-%m-%d_%H%M%S")"
RUN_LOG_PATH="${REPORTS_DIR}/run-${RUN_STAMP}.log"
TASK_LOG_PATH="${REPORTS_DIR}/task-runner.log"

log() {
  local message="$1"
  printf '[%s] %s\n' "$(date +"%Y-%m-%dT%H:%M:%S%z")" "${message}" | tee -a "${RUN_LOG_PATH}" >> "${TASK_LOG_PATH}"
}

run_spider() {
  local spider_name="$1"
  shift || true

  log "START ${spider_name}"
  if python -m scrapy crawl "${spider_name}" -s LOG_LEVEL=INFO "$@" >> "${RUN_LOG_PATH}" 2>&1; then
    log "END ${spider_name} exit=0"
    return 0
  fi

  local code=$?
  log "END ${spider_name} exit=${code}"
  return "${code}"
}

cd "${REPO_ROOT}"
log "RUN_START"

set +e
run_spider "afx_scraper"
AFX_EXIT=$?
run_spider "stockanalysis_scraper" -s HTTPCACHE_ENABLED=False
STOCKANALYSIS_EXIT=$?
set -e

if [[ "${AFX_EXIT}" -eq 0 && "${STOCKANALYSIS_EXIT}" -eq 0 ]]; then
  log "RUN_STATUS SUCCESS"
  exit 0
fi

log "RUN_STATUS FAILED afx_exit=${AFX_EXIT} stockanalysis_exit=${STOCKANALYSIS_EXIT}"
exit 1

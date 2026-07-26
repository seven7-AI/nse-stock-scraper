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

STATS_DIR="${REPORTS_DIR}/stats"
mkdir -p "${STATS_DIR}"

# Scrapy exits 0 even when a spider scrapes nothing, so the exit code alone cannot
# tell a healthy run from a silently empty one. The DataQualityGate extension writes
# reports/stats/<spider>-latest.json; this reads its quality_ok flag.
check_quality() {
  local spider_name="$1"
  local stats_path="${STATS_DIR}/${spider_name}-latest.json"

  if [[ ! -f "${stats_path}" ]]; then
    log "QUALITY ${spider_name} MISSING report=${stats_path}"
    return 1
  fi

  local summary
  summary="$(python - "${stats_path}" <<'PY'
import json, sys

with open(sys.argv[1], encoding="utf-8") as handle:
    report = json.load(handle)

print("{} items={} min={} db_ok={} db_failed={} {}".format(
    "OK" if report.get("quality_ok") else "FAILED",
    report.get("item_scraped_count"),
    report.get("min_items"),
    report.get("db_upsert_ok"),
    report.get("db_upsert_failed"),
    "; ".join(report.get("failures") or []),
).rstrip())
sys.exit(0 if report.get("quality_ok") else 1)
PY
)"
  local code=$?
  log "QUALITY ${spider_name} ${summary}"
  return "${code}"
}

run_spider() {
  local spider_name="$1"
  shift || true

  # Drop any stale report so a crash cannot leave yesterday's verdict behind.
  rm -f "${STATS_DIR}/${spider_name}-latest.json"

  log "START ${spider_name}"
  local code=0
  python -m scrapy crawl "${spider_name}" -s LOG_LEVEL=INFO "$@" >> "${RUN_LOG_PATH}" 2>&1 || code=$?
  log "END ${spider_name} exit=${code}"

  if [[ "${code}" -ne 0 ]]; then
    return "${code}"
  fi

  check_quality "${spider_name}" || return 2
  return 0
}

cd "${REPO_ROOT}"
log "RUN_START"

# Caching is disabled for both spiders so the quality gate measures a live fetch
# rather than a replay of an earlier cached response.
set +e
run_spider "afx_scraper" -s HTTPCACHE_ENABLED=False
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

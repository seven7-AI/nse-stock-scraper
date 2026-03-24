#!/usr/bin/env bash

set -euo pipefail

NO_GIT_PUSH="${NO_GIT_PUSH:-false}"
NO_GIT_COMMIT="${NO_GIT_COMMIT:-false}"
if [[ "${1:-}" == "--no-git-push" ]]; then
  NO_GIT_PUSH="true"
fi
if [[ "${1:-}" == "--no-git-commit" ]]; then
  NO_GIT_COMMIT="true"
  NO_GIT_PUSH="true"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS_DIR="${REPO_ROOT}/reports"
TASK_LOG_PATH="${REPORTS_DIR}/task-runner.log"
RUN_DATE="$(date +"%Y-%m-%d")"

mkdir -p "${REPORTS_DIR}"
cd "${REPO_ROOT}"

log_task() {
  local message="$1"
  printf '[%s] %s\n' "$(date +"%Y-%m-%dT%H:%M:%S%z")" "${message}" >> "${TASK_LOG_PATH}"
}

compose_run_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f deployment/docker-compose.yml run --rm scraper-job
    return
  fi
  docker-compose -f deployment/docker-compose.yml run --rm scraper-job
}

status_label="FAILED"

set +e
compose_run_cmd >> "${TASK_LOG_PATH}" 2>&1
run_exit=$?
set -e

if [[ "${run_exit}" -eq 0 ]]; then
  status_label="SUCCESS"
fi

log_task "DOCKER_RUN_STATUS ${status_label} exit=${run_exit}"

latest_run_log="$(ls -1t "${REPORTS_DIR}"/run-*.log 2>/dev/null | head -n 1 || true)"
tracked_paths=()
if [[ -n "${latest_run_log}" && -f "${latest_run_log}" ]]; then
  tracked_paths+=("${latest_run_log}")
fi
if [[ -f "${TASK_LOG_PATH}" ]]; then
  tracked_paths+=("${TASK_LOG_PATH}")
fi
if [[ -d "${REPORTS_DIR}/local_fallback" ]]; then
  while IFS= read -r fallback_file; do
    tracked_paths+=("${fallback_file}")
  done < <(ls -1 "${REPORTS_DIR}/local_fallback"/*.jsonl 2>/dev/null || true)
fi

if [[ "${#tracked_paths[@]}" -gt 0 ]]; then
  if [[ "${NO_GIT_COMMIT}" == "true" ]]; then
    log_task "GIT_COMMIT_SKIPPED"
  else
    git add -- "${tracked_paths[@]}"
    if ! git diff --cached --quiet; then
      git commit -m "chore(log): daily scraper run ${RUN_DATE} - ${status_label}" >> "${TASK_LOG_PATH}" 2>&1 || true
      if [[ "${NO_GIT_PUSH}" != "true" ]]; then
        current_branch="$(git branch --show-current)"
        if [[ -n "${current_branch}" ]]; then
          git push origin "${current_branch}" >> "${TASK_LOG_PATH}" 2>&1 || true
        fi
      fi
    else
      log_task "GIT_NO_CHANGES"
    fi
  fi
fi

exit "${run_exit}"

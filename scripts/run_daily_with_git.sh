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
# Quality reports are committed with the logs so item counts stay queryable in git
# history -- that is what makes a future silent degradation visible.
if [[ -d "${REPORTS_DIR}/stats" ]]; then
  while IFS= read -r stats_file; do
    tracked_paths+=("${stats_file}")
  done < <(ls -1 "${REPORTS_DIR}/stats"/*.json 2>/dev/null || true)
fi

git_exit=0

if [[ "${#tracked_paths[@]}" -gt 0 ]]; then
  if [[ "${NO_GIT_COMMIT}" == "true" ]]; then
    log_task "GIT_COMMIT_SKIPPED"
  else
    git add -- "${tracked_paths[@]}"
    if ! git diff --cached --quiet; then
      commit_exit=0
      git commit -m "chore(log): daily scraper run ${RUN_DATE} - ${status_label}" >> "${TASK_LOG_PATH}" 2>&1 || commit_exit=$?
      if [[ "${commit_exit}" -ne 0 ]]; then
        log_task "GIT_COMMIT_STATUS FAILED exit=${commit_exit}"
        git_exit="${commit_exit}"
      else
        log_task "GIT_COMMIT_STATUS SUCCESS"
        if [[ "${NO_GIT_PUSH}" != "true" ]]; then
          current_branch="$(git branch --show-current)"
          if [[ -z "${current_branch}" ]]; then
            log_task "GIT_PUSH_STATUS SKIPPED reason=detached_head"
            git_exit=1
          else
            # origin may have moved (CI or a manual commit); rebase onto it first so
            # the push is not silently rejected as non-fast-forward.
            rebase_exit=0
            git pull --rebase --autostash origin "${current_branch}" >> "${TASK_LOG_PATH}" 2>&1 || rebase_exit=$?
            if [[ "${rebase_exit}" -ne 0 ]]; then
              # Never leave the working tree mid-rebase for the next run to trip over.
              git rebase --abort >> "${TASK_LOG_PATH}" 2>&1 || true
              log_task "GIT_PUSH_STATUS FAILED exit=${rebase_exit} reason=rebase_conflict"
              git_exit="${rebase_exit}"
            else
              push_exit=0
              git push origin "${current_branch}" >> "${TASK_LOG_PATH}" 2>&1 || push_exit=$?
              if [[ "${push_exit}" -ne 0 ]]; then
                log_task "GIT_PUSH_STATUS FAILED exit=${push_exit}"
                git_exit="${push_exit}"
              else
                log_task "GIT_PUSH_STATUS SUCCESS branch=${current_branch}"
              fi
            fi
          fi
        fi
      fi
    else
      log_task "GIT_NO_CHANGES"
    fi
  fi
fi

# A scrape failure outranks a publishing failure, but neither may exit 0.
if [[ "${run_exit}" -ne 0 ]]; then
  exit "${run_exit}"
fi
exit "${git_exit}"

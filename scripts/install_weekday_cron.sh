#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_TZ_NAME="Africa/Nairobi"
CRON_EXPR="0 9 * * *"
CRON_CMD="cd ${REPO_ROOT} && docker compose -f deployment/docker-compose.yml run --rm scraper-job >> ${REPO_ROOT}/reports/task-runner.log 2>&1"
CRON_LINE="${CRON_EXPR} ${CRON_CMD}"

mkdir -p "${REPO_ROOT}/reports"

EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "${EXISTING_CRONTAB}" | grep -Fq "${CRON_CMD}"; then
  echo "Cron entry already exists:"
  echo "${CRON_LINE}"
  exit 0
fi

{
  printf '%s\n' "${EXISTING_CRONTAB}"
  printf 'CRON_TZ=%s\n' "${CRON_TZ_NAME}"
  printf '%s\n' "${CRON_LINE}"
} | crontab -

echo "Installed weekday cron schedule at 09:00 ${CRON_TZ_NAME}:"
echo "${CRON_LINE}"

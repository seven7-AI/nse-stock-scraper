#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_TZ_NAME="Africa/Nairobi"
CRON_HOUR="09"
CRON_EXPR="0 ${CRON_HOUR} * * *"
CRON_CMD="cd ${REPO_ROOT} && bash scripts/run_daily_with_git.sh"
CRON_LINE="${CRON_EXPR} ${CRON_CMD}"
INSTALLED_COPY="${REPO_ROOT}/deployment/cron/daily-cron.installed"

mkdir -p "${REPO_ROOT}/reports"

EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "${EXISTING_CRONTAB}" | grep -Fq "${CRON_CMD}"; then
  echo "Cron entry already exists:"
  echo "${CRON_LINE}"
  exit 0
fi

# This appends; it never rewrites the crontab. Note that another project running
# `crontab <file>` replaces the whole user crontab and will silently remove this
# entry -- that is what happened on 2026-07-05. Use `make cron-verify` to detect it.
{
  printf '%s\n' "${EXISTING_CRONTAB}"
  printf 'CRON_TZ=%s\n' "${CRON_TZ_NAME}"
  printf '%s\n' "${CRON_LINE}"
} | crontab -

printf 'CRON_TZ=%s\n%s\n' "${CRON_TZ_NAME}" "${CRON_LINE}" > "${INSTALLED_COPY}"

echo "Installed daily cron schedule at ${CRON_HOUR}:00 ${CRON_TZ_NAME}:"
echo "${CRON_LINE}"
echo

# CRON_TZ is a Vixie-cron extension. Every historical run fired at 09:00 host-local
# rather than 09:00 Nairobi, so report both times instead of assuming CRON_TZ applies.
echo "Verification:"
echo "  host local now  : $(date +'%H:%M %Z')"
echo "  ${CRON_TZ_NAME} now : $(TZ="${CRON_TZ_NAME}" date +'%H:%M %Z')"
echo "  intended fire   : ${CRON_HOUR}:00 ${CRON_TZ_NAME}"
echo "                  = $(TZ="${CRON_TZ_NAME}" date -d "${CRON_HOUR}:00" +'%H:%M' | \
      xargs -I{} date -d "TZ=\"${CRON_TZ_NAME}\" {}" +'%H:%M %Z' 2>/dev/null || echo '?') host local"
echo
echo "Compare against the first observed run in reports/task-runner.log. If it fires at"
echo "${CRON_HOUR}:00 host-local instead, this cron ignores CRON_TZ: set CRON_HOUR to the"
echo "equivalent host-local hour and re-install."

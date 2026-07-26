.PHONY: help install test lint docker-run cron-install cron-verify

help:
	@echo "Targets: install, test, lint, docker-run, cron-install, cron-verify"

install:
	python -m pip install --upgrade pip
	pip install -r requirements.txt

test:
	python3 -m unittest discover -s tests -p "test_*.py" -v

lint:
	pip install flake8
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
	flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics

docker-run:
	docker compose -f deployment/docker-compose.yml run --rm scraper-job

cron-install:
	bash scripts/install_daily_cron.sh

# Fails if the daily entry is missing from the live crontab. Another project running
# `crontab <file>` silently replaces the whole user crontab; that removed this job on
# 2026-07-05 and went unnoticed for three weeks.
cron-verify:
	@crontab -l 2>/dev/null | grep -Fq 'scripts/run_daily_with_git.sh' \
		&& echo "OK: daily scraper cron entry is installed" \
		|| { echo "MISSING: daily scraper cron entry is not installed. Run: make cron-install"; exit 1; }

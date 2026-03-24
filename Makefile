.PHONY: help install test lint docker-run cron-install

help:
	@echo "Targets: install, test, lint, docker-run, cron-install"

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

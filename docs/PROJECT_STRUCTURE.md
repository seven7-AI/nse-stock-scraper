# Project Structure

## High-level layout

```text
nse-stock-scraper/
├── deployment/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── cron/
│       └── daily-cron.example
├── scripts/
│   ├── run_daily_job.sh
│   ├── run_daily_with_git.sh
│   └── install_daily_cron.sh
├── nse_scraper/
│   ├── spiders/
│   ├── db/
│   ├── pipelines.py
│   └── settings.py
├── config/
│   ├── .env.example
│   └── .env.docker
├── docs/
│   ├── INDEX.md
│   ├── ARCHITECTURE.md
│   ├── QUICKSTART.md
│   ├── DOCKER.md
│   └── SUPABASE_SETUP.md
├── reports/
├── tests/
├── scrapy.cfg
└── README.md
```

## Structure intent

- `deployment/cron/` keeps schedulers and infra-facing templates.
- `scripts/` contains executable operational scripts (Linux-first).
- `nse_scraper/` remains the Scrapy application package.
- `docs/` contains operator and developer guidance.
- `config/` contains env templates only.

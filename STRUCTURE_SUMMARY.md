# Project Organization Summary

This repository is organized around a Scrapy app with multi-backend storage support.

## Top-level layout

```
nse-stock-scraper/
├── nse_scraper/            # Scraper package and backend adapters
├── docs/                   # Documentation
├── config/                 # .env templates
├── alembic/                # PostgreSQL migrations
├── sql/                    # SQL schema and helper scripts
├── tests/                  # Unit/integration tests
├── docker-compose.yml      # Local services (mongo, postgres, scraper)
├── Dockerfile
├── requirements.txt
└── README.md
```

## Notes

- MongoDB remains supported and is the default backend.
- PostgreSQL support uses SQLAlchemy and Alembic.
- Supabase support uses the same logical schema as PostgreSQL.
- `stock_notification.py` is retained as a placeholder utility with messaging disabled.

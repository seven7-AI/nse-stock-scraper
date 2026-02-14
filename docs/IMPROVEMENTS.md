# Improvements Log

## 2026-02 multi-backend update

- Added backend abstraction for stock storage in `nse_scraper/db/backends.py`.
- Kept MongoDB support intact as a first-class backend.
- Added PostgreSQL support via SQLAlchemy models and Alembic migrations.
- Added Supabase client path with the same logical schema and upsert key.
- Added Alembic config and initial migration for `stock_data`.
- Added SQL scripts for table creation and upsert helper function.
- Removed Africa's Talking runtime integration and dependency.
- Removed text scheduler integration references from runtime and deployment docs.
- Converted `stock_notification.py` into a placeholder query utility with no sending behavior.
- Updated env templates, Docker config, CI workflows, tests, and documentation to match the new architecture.

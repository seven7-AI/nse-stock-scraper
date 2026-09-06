# Structure Summary

Repository now follows Linux operations with a local SQLite runtime:

- Windows scheduler scripts removed.
- Docker one-shot job added (`scraper-job`).
- Cron installer script added for daily 09:00 `Africa/Nairobi`.
- Runtime configuration standardized to root `.env`.
- Storage is local SQLite at `data/nse_scraper.sqlite3` (host-mounted); Supabase
  remains selectable with `DB_BACKEND=supabase`.
- Documentation aligned with Docker + cron flow.

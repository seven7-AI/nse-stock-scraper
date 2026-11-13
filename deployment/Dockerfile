# Multi-stage build for NSE Stock Scraper
FROM python:3.14-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.14-slim

WORKDIR /app

# Install runtime dependencies.
#
# tesseract-ocr and poppler-utils are not optional extras: the Nairobi Securities
# Exchange publishes its daily price list only as a scanned image, and since
# 2026-11-06 that list is the source of the canonical close for every instrument.
# Without pdftoppm and tesseract in the image, nse_pricelist_job raises on every
# scheduled run and the timeline stops moving. tesseract-ocr-eng carries the English
# traineddata the parser is measured against.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /usr/local /usr/local

# Copy application code and scripts
COPY nse_scraper/ ./nse_scraper/
COPY scripts/ ./scripts/
COPY scrapy.cfg .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security. uid 1000 matches the host user that owns reports/
# and data/, so the bind-mounted directories are writable from inside the container.
# /app/data is created here so the mount point exists and is owned by scraper even when
# the compose volume is absent (an ad-hoc `docker run` still gets a working database).
RUN useradd -m -u 1000 scraper \
    && mkdir -p /app/data /app/reports \
    && chmod +x /app/scripts/*.sh \
    && chown -R scraper:scraper /app
USER scraper

# Health check: validate whichever backend is selected, not a hardcoded one. For sqlite
# that means the database directory must be writable -- catching a missing or read-only
# ../data bind mount before a crawl silently sends 63 rows to the fallback file.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; b=os.getenv('DB_BACKEND','sqlite').lower(); assert b in ('sqlite','supabase'), b; p=os.getenv('SQLITE_DB_PATH','data/nse_scraper.sqlite3') if b=='sqlite' else None; assert not p or os.access(os.path.dirname(os.path.abspath(p)), os.W_OK); assert b!='supabase' or (os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_KEY'))" || exit 1

# Run scraper by default
ENTRYPOINT ["python", "-m", "scrapy"]
CMD ["crawl", "afx_scraper"]

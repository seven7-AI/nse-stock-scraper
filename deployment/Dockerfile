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

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
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

# Create non-root user for security
RUN useradd -m -u 1000 scraper && chmod +x /app/scripts/*.sh && chown -R scraper:scraper /app
USER scraper

# Health check (Supabase-only runtime)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; assert os.getenv('DB_BACKEND', 'supabase').lower() == 'supabase'; assert os.getenv('SUPABASE_URL'); assert os.getenv('SUPABASE_KEY')" || exit 1

# Run scraper by default
ENTRYPOINT ["python", "-m", "scrapy"]
CMD ["crawl", "afx_scraper"]

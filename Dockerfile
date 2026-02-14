# Multi-stage build for NSE Stock Scraper
FROM python:3.14-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.14-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application code and sample env
COPY nse_scraper/ ./nse_scraper/
COPY config/.env.example .env.example
COPY scrapy.cfg .

# Set environment variables
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN useradd -m -u 1000 scraper && chown -R scraper:scraper /app
USER scraper

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; backend=os.getenv('DB_BACKEND','mongo').lower(); \
if backend=='mongo': import pymongo; pymongo.MongoClient(os.getenv('MONGODB_URI')).admin.command('ping'); \
elif backend=='postgres': from sqlalchemy import create_engine, text; eng=create_engine(os.getenv('SQL_DATABASE_URL')); conn=eng.connect(); conn.execute(text('SELECT 1')); conn.close(); eng.dispose(); \
elif backend=='supabase': assert os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_KEY'); \
else: raise SystemExit(1)" || exit 1

# Run scraper by default
ENTRYPOINT ["scrapy"]
CMD ["crawl", "afx_scraper"]

FROM python:3.12-slim AS builder

WORKDIR /app

# System deps for spacy, lancedb, and readability-lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy everything needed for install
COPY pyproject.toml .
COPY core/ core/
COPY config/ config/
COPY autonomy_matrix.json* ./

# Install Python dependencies
RUN pip install --no-cache-dir .

# Download spacy model
RUN python -m spacy download en_core_web_sm

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Runtime libs only (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY core/ core/
COPY vault/ vault/
COPY memory/ memory/
COPY config/ config/
COPY autonomy_matrix.json* ./
COPY settings.json* providers.toml* ./
COPY brand/ brand/
COPY frontend/ frontend/
COPY docker/healthcheck.py docker/

# Expose FastAPI + MCP ports
EXPOSE 8420 8421

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python docker/healthcheck.py || exit 1

# Start FastAPI server
CMD ["python", "-m", "uvicorn", "core.interface.api:app", "--host", "0.0.0.0", "--port", "8420"]

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only the dependency file
COPY pyproject.toml .

# Install dependencies in a way that cleans up after each step
RUN pip install --no-cache-dir wheel && \
    pip install --no-cache-dir -e . && \
    rm -rf /root/.cache/pip

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy project files
COPY . .

# Create directory for static files and logs
RUN mkdir -p /app/staticfiles /app/logs

# Expose port
EXPOSE 8000

# Make scripts executable
RUN chmod +x run.sh scripts/*.sh

# Run the application
CMD ["./run.sh"]
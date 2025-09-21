#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Nura Vault Backend Production Server...${NC}"

# Check if we're in a Docker environment (this file exists in Docker containers)
if [ -f "/.dockerenv" ]; then
    echo -e "${GREEN}Running in Docker environment, setting DB_HOST=db...${NC}"
    export DB_HOST=db
fi

# Debug database connection info
echo -e "${YELLOW}Database connection info:${NC}"
echo "DB_HOST: ${DB_HOST}"
echo "DB_PORT: ${DB_PORT}"
echo "DB_NAME: ${DB_NAME}"
echo "DB_USER: ${DB_USER}"
echo "DB_PASSWORD: ${DB_PASSWORD}"
echo "AWS_SECRET_NAME: ${AWS_SECRET_NAME}"
echo "AWS_DB_SECRET_NAME: ${AWS_DB_SECRET_NAME}"
echo "AWS_REGION: ${AWS_REGION}"
echo "DB_PASSWORD is set: $(if [ -n "$DB_PASSWORD" ]; then echo 'YES'; else echo 'NO'; fi)"

# Wait for PostgreSQL to be ready
echo -e "${GREEN}Waiting for PostgreSQL...${NC}"
# Use DB_HOST and DB_PORT from environment, with fallbacks for local development
while ! pg_isready -h ${DB_HOST:-db} -p ${DB_PORT:-5432} -U ${DB_USER:-postgres}; do
    sleep 1
done

# Create logs directory if it doesn't exist
echo -e "${GREEN}Creating logs directory if it doesn't exist...${NC}"
mkdir -p /app/logs


# Run database migrations
echo -e "${GREEN}Running database migrations...${NC}"
python manage.py migrate

# Collect static files for API documentation
echo -e "${GREEN}Collecting static files...${NC}"
python manage.py collectstatic --noinput

# Install missing dependencies
echo -e "${GREEN}Installing missing dependencies...${NC}"
pip install --no-cache-dir langchain>=0.1.0 langchain-openai>=0.1.0

# Function to handle shutdown
cleanup() {
    echo -e "${YELLOW}Shutting down all services...${NC}"
    # Kill all background processes
    jobs -p | xargs -r kill
    exit 0
}

# Set up trap to handle termination signals
trap cleanup SIGINT SIGTERM

# Run APY monitor cron job every hour in the background
echo -e "${GREEN}Starting APY monitor cron job (runs every hour)...${NC}"
# Create logs directory for APY monitor if it doesn't exist
mkdir -p logs

# Function to run the APY monitor job
run_apy_monitor() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local log_file="logs/apy_monitor_${timestamp}.log"
    echo -e "${GREEN}Running APY monitor job at $(date)${NC}" | tee -a $log_file
    python data/workers/cron_service/cron_job.py 2>&1 | tee -a $log_file
    echo -e "${GREEN}APY monitor job completed at $(date)${NC}" | tee -a $log_file
}

# Function to run the Yield monitor job
run_yield_monitor() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local log_file="logs/yield_monitor_${timestamp}.log"
    echo -e "${GREEN}Running Yield monitor job at $(date)${NC}" | tee -a $log_file
    python data/workers/cron_service/yield_monitor_worker.py 2>&1 | tee -a $log_file
    echo -e "${GREEN}Yield monitor job completed at $(date)${NC}" | tee -a $log_file
}

# Function to run the Vault worker job
run_vault_worker() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local log_file="logs/vault_worker_${timestamp}.log"
    echo -e "${GREEN}Running Vault worker job at $(date)${NC}" | tee -a $log_file
    python data/workers/cron_service/vault_worker.py 2>&1 | tee -a $log_file
    echo -e "${GREEN}Vault worker job completed at $(date)${NC}" | tee -a $log_file
}

# Run the APY monitor job immediately at startup
run_apy_monitor

# Run the Yield monitor job immediately at startup
run_yield_monitor

# Run the Vault worker job immediately at startup
run_vault_worker


# Start a background process to run the APY monitor job every hour
(
    while true; do
        # Sleep for 1 hour (3600 seconds)
        sleep 3600
        run_apy_monitor
    done
) &
echo -e "${GREEN}APY monitor hourly job scheduler started in background${NC}"

# Start a background process to run the Yield monitor job every hour
(
    while true; do
        # Sleep for 1 hour (3600 seconds)
        sleep 3600
        run_yield_monitor
    done
) &
echo -e "${GREEN}Yield monitor hourly job scheduler started in background${NC}"

# # # Start a background process to run the Vault worker job every 30 minutes
(
    while true; do
        # Sleep for 30 minutes (1800 seconds)
        sleep 1800
        run_vault_worker
    done
) &
echo -e "${GREEN}Vault worker job scheduler (30-minute interval) started in background${NC}"


# Start Gunicorn in foreground (this keeps the container alive)
echo -e "${GREEN}Starting Gunicorn server...${NC}"
gunicorn defai_backend.wsgi:application -c /app/gunicorn_config.py
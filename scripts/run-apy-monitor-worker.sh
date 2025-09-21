#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Script to run the APY monitor worker as a background process
echo -e "${GREEN}Starting APY monitor worker...${NC}"

# Check if we're using AWS Secrets Manager
if [ -n "$AWS_SECRET_NAME" ]; then
    echo -e "${GREEN}Using AWS Secrets Manager for configuration...${NC}"
    # AWS credentials are expected to be provided via environment variables or instance profile
    # No need to load .env file
elif [ -f ".env" ]; then
    # Load .env file if it exists (for local development)
    echo -e "${GREEN}Loading environment variables from .env file...${NC}"
    source .env
else
    # Check if essential environment variables are already set (Railway, Docker, etc.)
    if [ -n "$DB_HOST" ] || [ -n "$DATABASE_URL" ] || [ -n "$RAILWAY_ENVIRONMENT" ]; then
        echo -e "${GREEN}Using environment variables from deployment platform...${NC}"
    else
        echo -e "${RED}Error: .env file not found and no environment variables detected!${NC}"
        echo -e "${YELLOW}Please create a .env file with your environment variables or set AWS_SECRET_NAME.${NC}"
        exit 1
    fi
fi

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Create a log directory if it doesn't exist
LOG_DIR="logs"
mkdir -p $LOG_DIR

# Get the current timestamp for the log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/apy_monitor_${TIMESTAMP}.log"

# Function to run the APY monitor job
run_apy_monitor() {
    echo -e "${GREEN}Running APY monitor job at $(date)${NC}" | tee -a $LOG_FILE
    python data/workers/cron_service/cron_job.py >> $LOG_FILE 2>&1
    echo -e "${GREEN}APY monitor job completed at $(date)${NC}" | tee -a $LOG_FILE
}

# Function to handle script termination
cleanup() {
    echo -e "${YELLOW}Shutting down APY monitor worker...${NC}"
    exit 0
}

# Set up trap to handle termination signals
trap cleanup SIGINT SIGTERM

# Configure interval from environment variable (default: 3600 seconds = 1 hour)
APY_MONITOR_INTERVAL=${APY_MONITOR_INTERVAL_SECONDS:-3600}
echo -e "${GREEN}APY Monitor interval set to ${APY_MONITOR_INTERVAL} seconds${NC}"

# Run the APY monitor job immediately
echo -e "${GREEN}Starting initial APY monitor job...${NC}"
run_apy_monitor

# Start the configurable cron-like loop
echo -e "${GREEN}APY monitor worker running with ${APY_MONITOR_INTERVAL}s interval. Press Ctrl+C to stop.${NC}"
while true; do
    # Format next run time
    if command -v gdate >/dev/null 2>&1; then
        # macOS with GNU date
        NEXT_RUN_TIME=$(gdate -d "+${APY_MONITOR_INTERVAL} seconds" "+%Y-%m-%d %H:%M:%S")
    else
        # Linux date or fallback
        NEXT_RUN_TIME=$(date -d "+${APY_MONITOR_INTERVAL} seconds" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || date -v+${APY_MONITOR_INTERVAL}S "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "$(date "+%Y-%m-%d %H:%M:%S")")
    fi
    
    echo -e "${GREEN}Next APY monitor job will run in ${APY_MONITOR_INTERVAL} seconds (${NEXT_RUN_TIME})${NC}"
    
    # Sleep for the configured interval
    sleep $APY_MONITOR_INTERVAL
    
    # Run the APY monitor job
    run_apy_monitor
done

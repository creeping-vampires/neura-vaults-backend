#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Simple agent worker script for production
echo -e "${GREEN}Starting Simple Agent Worker...${NC}"

# Check if we're using AWS Secrets Manager
if [ -n "$AWS_SECRET_NAME" ]; then
    echo -e "${GREEN}Using AWS Secrets Manager for configuration...${NC}"
elif [ -f ".env" ]; then
    echo -e "${GREEN}Loading environment variables from .env file...${NC}"
    source .env
else
    # Check if essential environment variables are already set (Railway, Docker, etc.)
    if [ -n "$DB_HOST" ] || [ -n "$DATABASE_URL" ] || [ -n "$RAILWAY_ENVIRONMENT" ]; then
        echo -e "${GREEN}Using environment variables from deployment platform...${NC}"
    else
        echo -e "${RED}Error: .env file not found and no environment variables detected!${NC}"
        exit 1
    fi
fi

# Create a log directory if it doesn't exist
LOG_DIR="logs"
mkdir -p $LOG_DIR

# Get the current timestamp for the log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/simple_agent_worker_${TIMESTAMP}.log"

# Function to run the simple agent worker
run_simple_agent_worker() {
    echo -e "${GREEN}Running simple agent worker at $(date)${NC}" | tee -a $LOG_FILE
    python data/workers/cron_service/simple_agent_worker.py 2>&1 | tee -a $LOG_FILE
    local exit_code=${PIPESTATUS[0]}
    echo -e "${GREEN}Simple agent worker completed at $(date) with exit code: $exit_code${NC}" | tee -a $LOG_FILE
    return $exit_code
}

# Function to handle script termination
cleanup() {
    echo -e "${YELLOW}Shutting down simple agent worker...${NC}"
    exit 0
}

# Set up trap to handle termination signals
trap cleanup SIGINT SIGTERM

# Configure interval from environment variable (default: 300 seconds = 5 minutes)
AGENT_WORKER_INTERVAL=${AGENT_WORKER_INTERVAL_SECONDS:-300}
echo -e "${GREEN}Simple Agent Worker interval set to ${AGENT_WORKER_INTERVAL} seconds${NC}"

# Run the agent worker job immediately
echo -e "${GREEN}Starting simple agent worker job...${NC}"
run_simple_agent_worker

# Start the configurable cron-like loop
echo -e "${GREEN}Simple agent worker running with ${AGENT_WORKER_INTERVAL}s interval. Press Ctrl+C to stop.${NC}"
while true; do
    # Format next run time
    if command -v gdate >/dev/null 2>&1; then
        # macOS with GNU date
        NEXT_RUN_TIME=$(gdate -d "+${AGENT_WORKER_INTERVAL} seconds" "+%Y-%m-%d %H:%M:%S")
    else
        # Linux date or fallback
        NEXT_RUN_TIME=$(date -d "+${AGENT_WORKER_INTERVAL} seconds" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || date -v+${AGENT_WORKER_INTERVAL}S "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "$(date "+%Y-%m-%d %H:%M:%S")")
    fi
    
    echo -e "${GREEN}Next simple agent worker job will run in ${AGENT_WORKER_INTERVAL} seconds (${NEXT_RUN_TIME})${NC}"
    
    # Sleep for the configured interval
    sleep $AGENT_WORKER_INTERVAL
    
    # Run the agent worker job
    run_simple_agent_worker
done

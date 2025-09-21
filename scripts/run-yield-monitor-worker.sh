#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Script to run the yield monitor worker as a background process
echo -e "${GREEN}Starting Yield Monitor Worker...${NC}"

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

# Validate required environment variables for yield monitoring
required_vars=("COMPOUNDING_WALLET_PRIVATE_KEY" "RPC_URL" "WHITELIST_REGISTRY_ADDRESS" "YIELD_ALLOCATOR_VAULT_ADDRESS" "AI_AGENT_ADDRESS")
missing_vars=()

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        missing_vars+=("$var")
    fi
done

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required environment variables:${NC}"
    for var in "${missing_vars[@]}"; do
        echo -e "${RED}  - $var${NC}"
    done
    echo -e "${YELLOW}Please set these variables in your .env file or environment.${NC}"
    exit 1
fi

# Display configuration
echo -e "${GREEN}Configuration:${NC}"
echo -e "  RPC URL: ${RPC_URL}"
echo -e "  WhitelistRegistry: ${WHITELIST_REGISTRY_ADDRESS}"
echo -e "  YieldAllocatorVault: ${YIELD_ALLOCATOR_VAULT_ADDRESS}"
echo -e "  AIAgent: ${AI_AGENT_ADDRESS}"
echo -e "  Yield Threshold: ${YIELD_THRESHOLD:-0.001%}"
echo -e "  Min Claim Amount: \$${MIN_CLAIM_AMOUNT:-1}"
echo -e "  Max Gas Cost: \$${MAX_GAS_COST_USD:-5}"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Create a log directory if it doesn't exist
LOG_DIR="logs"
mkdir -p $LOG_DIR

# Get the current timestamp for the log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/yield_monitor_${TIMESTAMP}.log"

# Function to run the yield monitor job
run_yield_monitor() {
    echo -e "${GREEN}Running yield monitor job at $(date)${NC}" | tee -a $LOG_FILE
    python data/workers/cron_service/yield_monitor_worker.py >> $LOG_FILE 2>&1
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}Yield monitor job completed successfully at $(date)${NC}" | tee -a $LOG_FILE
    else
        echo -e "${RED}Yield monitor job failed with exit code $exit_code at $(date)${NC}" | tee -a $LOG_FILE
    fi
    
    return $exit_code
}

# Function to handle script termination
cleanup() {
    echo -e "${YELLOW}Shutting down yield monitor worker...${NC}"
    exit 0
}

# Set up trap to handle termination signals
trap cleanup SIGINT SIGTERM

# Configure interval from environment variable (default: 3600 seconds = 1 hour)
YIELD_MONITOR_INTERVAL=${YIELD_MONITOR_INTERVAL_SECONDS:-3600}
echo -e "${GREEN}Yield Monitor interval set to ${YIELD_MONITOR_INTERVAL} seconds${NC}"

# Check if running in one-shot mode
if [ "$1" = "--once" ]; then
    echo -e "${GREEN}Running yield monitor in one-shot mode...${NC}"
    run_yield_monitor
    exit $?
fi

# Run the yield monitor job immediately
echo -e "${GREEN}Starting initial yield monitor job...${NC}"
run_yield_monitor

# Start the configurable cron-like loop
echo -e "${GREEN}Yield monitor worker running with ${YIELD_MONITOR_INTERVAL}s interval. Press Ctrl+C to stop.${NC}"

while true; do
    # Format next run time
    if command -v gdate >/dev/null 2>&1; then
        # macOS with GNU date
        NEXT_RUN_TIME=$(gdate -d "+${YIELD_MONITOR_INTERVAL} seconds" "+%Y-%m-%d %H:%M:%S")
    else
        # Linux date or fallback
        NEXT_RUN_TIME=$(date -d "+${YIELD_MONITOR_INTERVAL} seconds" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || date -v+${YIELD_MONITOR_INTERVAL}S "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "$(date "+%Y-%m-%d %H:%M:%S")")
    fi
    
    echo -e "${GREEN}Next yield monitor job will run in ${YIELD_MONITOR_INTERVAL} seconds (${NEXT_RUN_TIME})${NC}"
    
    # Sleep for the configured interval
    sleep $YIELD_MONITOR_INTERVAL
    
    # Run the yield monitor job
    run_yield_monitor
done

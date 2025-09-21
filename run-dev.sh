#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting DefAI Backend Development Server Setup...${NC}"


# Create logs directory if it doesn't exist
echo -e "${GREEN}Creating logs directory if it doesn't exist...${NC}"
mkdir -p logs


# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo -e "${YELLOW}Please create a .env file with your environment variables.${NC}"
    exit 1
fi

# Load environment variables from .env file
echo -e "${GREEN}Loading environment variables from .env file...${NC}"
export $(cat .env | grep -v '^#' | xargs)

# Force development database settings
export USE_SQLITE=true
unset DATABASE_URL

# # Delete the existing database file if it exists
# if [ -f "db.sqlite3" ]; then
#     echo -e "${GREEN}Deleting existing db.sqlite3 file...${NC}"
#     rm db.sqlite3
# else
#     echo -e "${GREEN}No existing db.sqlite3 file found.${NC}"
# fi

# Run migrations
echo -e "${GREEN}Running database migrations...${NC}"
uv run python manage.py makemigrations
uv run python manage.py migrate

# Create superuser
echo -e "${GREEN}Creating superuser...${NC}"
DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=admin DJANGO_SUPERUSER_EMAIL=admin@example.com uv run python manage.py createsuperuser --noinput

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
    uv run python data/workers/cron_service/cron_job.py 2>&1 | tee -a $log_file
    echo -e "${GREEN}APY monitor job completed at $(date)${NC}" | tee -a $log_file
}

# Function to run the Yield monitor job
run_yield_monitor() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local log_file="logs/yield_monitor_${timestamp}.log"
    echo -e "${GREEN}Running Yield monitor job at $(date)${NC}" | tee -a $log_file
    uv run python data/workers/cron_service/yield_monitor_worker.py 2>&1 | tee -a $log_file
    echo -e "${GREEN}Yield monitor job completed at $(date)${NC}" | tee -a $log_file
}

# Function to run the Agent worker job
run_agent_worker() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local log_file="logs/agent_worker_${timestamp}.log"
    echo -e "${GREEN}Running Agent worker job at $(date)${NC}" | tee -a $log_file
    uv python manage.py run_agent_worker --single-run 2>&1 | tee -a $log_file
    echo -e "${GREEN}Agent worker job completed at $(date)${NC}" | tee -a $log_file
}

# Run the APY monitor job immediately at startup
run_apy_monitor

# Run the Yield monitor job immediately at startup
run_yield_monitor

# Run the Agent worker job immediately at startup
# run_agent_worker

# Start a background process to run the APY monitor job every hour
# (
#     while true; do
#         # Sleep for 5 minutes (300 seconds)
#         sleep 300
#         run_apy_monitor
#     done
# ) &
# echo -e "${GREEN}APY monitor hourly job scheduler started in background${NC}"

# Start a background process to run the Yield monitor job every hour
# (
#     while true; do
#         # Sleep for 30 minutes (1800 seconds)
#         sleep 1800
#         run_yield_monitor
#     done
# ) &
# echo -e "${GREEN}Yield monitor hourly job scheduler started in background${NC}"

# # Start a background process to run the Agent worker job every day
# (
#     while true; do
#         # Sleep for 24 hours (86400 seconds)
#         sleep 86400
#         run_agent_worker
#     done
# ) &
# echo -e "${GREEN}Agent worker daily job scheduler started in background${NC}"




# Start the server
echo -e "${GREEN}Starting development server...${NC}"
echo -e "${YELLOW}API Documentation available at:${NC}"
echo -e "  - Swagger UI:  http://localhost:8000/api/docs/"
echo -e "  - ReDoc UI:    http://localhost:8000/api/redoc/"
echo -e "${YELLOW}Press CTRL+C to stop the server${NC}"
uv run python manage.py runserver
#!/bin/bash

# Script to run Docker Compose with AWS credentials and database password
# This avoids storing credentials in .env files

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting Docker containers with AWS credentials...${NC}"

# Check if .env file exists, create an empty one if it doesn't
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}.env file not found, creating an empty one to avoid Docker Compose errors${NC}"
    touch .env
fi

# Check if AWS credentials are provided as arguments or environment variables
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo -e "${YELLOW}AWS credentials not found in environment variables.${NC}"
    
    # Check if at least two arguments are provided (even if empty)
    if [ "$#" -lt 2 ]; then
        echo -e "${RED}Error: Not enough arguments provided.${NC}"
        echo "Usage: $0 <aws_access_key_id> <aws_secret_access_key> [db_password] [docker-compose command]"
        exit 1
    fi
    
    # Check if the first two arguments are empty strings
    if [ -z "$1" ] && [ -z "$2" ]; then
        echo -e "${YELLOW}Empty AWS credentials provided, using IAM role instead.${NC}"
    else
        # Set AWS credentials from arguments
        export AWS_ACCESS_KEY_ID=$1
        export AWS_SECRET_ACCESS_KEY=$2
        echo -e "${GREEN}Using AWS credentials from command line arguments.${NC}"
    fi
    
    # Remove the first two arguments (AWS credentials or empty strings)
    shift 2
else
    echo -e "${GREEN}Using AWS credentials from environment variables.${NC}"
fi

# Function to securely get database credentials
get_db_credentials() {
    # Check if we need to get DB credentials from AWS Secrets Manager
    if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ] && [ -n "$AWS_SECRET_NAME" ]; then
        echo -e "${YELLOW}Attempting to fetch database credentials from AWS Secrets Manager...${NC}"
        
        # Use the verify_aws_secrets.py script to get the credentials
        if [ -f "./scripts/verify_aws_secrets.py" ]; then
            # Run the script and capture the output
            SECRET_JSON=$(python3 ./scripts/verify_aws_secrets.py --secret-name "${AWS_SECRET_NAME:-defai/backend}" --region "${AWS_REGION:-us-east-1}" --json-output 2>/dev/null)
            
            # Check if we got valid JSON
            if [ $? -eq 0 ] && [ -n "$SECRET_JSON" ]; then
                # Extract database credentials from JSON
                DB_NAME_FROM_AWS=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('DB_NAME', ''))")
                DB_USER_FROM_AWS=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('DB_USER', ''))")
                DB_PASSWORD_FROM_AWS=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('DB_PASSWORD', ''))")
                
                # Use AWS values if they exist and aren't already set
                if [ -n "$DB_NAME_FROM_AWS" ] && [ -z "$DB_NAME" ]; then
                    export DB_NAME="$DB_NAME_FROM_AWS"
                    echo -e "${GREEN}Using DB_NAME from AWS Secrets Manager.${NC}"
                fi
                
                if [ -n "$DB_USER_FROM_AWS" ] && [ -z "$DB_USER" ]; then
                    export DB_USER="$DB_USER_FROM_AWS"
                    echo -e "${GREEN}Using DB_USER from AWS Secrets Manager.${NC}"
                fi
                
                if [ -n "$DB_PASSWORD_FROM_AWS" ] && [ -z "$DB_PASSWORD" ]; then
                    export DB_PASSWORD="$DB_PASSWORD_FROM_AWS"
                    echo -e "${GREEN}Using DB_PASSWORD from AWS Secrets Manager.${NC}"
                fi
            else
                echo -e "${YELLOW}Could not fetch credentials from AWS Secrets Manager.${NC}"
            fi
        fi
    fi
    
    # Check if DB password is provided as the next argument
    if [ "$#" -gt 0 ]; then
        # If the argument doesn't start with a dash, assume it's the DB password
        if [[ "$1" != -* ]]; then
            export DB_PASSWORD="$1"
            shift 1
            echo -e "${GREEN}Using database password from command line argument: '$DB_PASSWORD'${NC}"
        fi
    fi
    
    # Check if we have the required DB_PASSWORD
    if [ -z "$DB_PASSWORD" ]; then
        echo -e "${RED}Error: Database password is required but not provided.${NC}"
        echo "Please set the DB_PASSWORD environment variable or provide it as an argument."
        return 1
    fi
    
    # Set defaults for DB_NAME and DB_USER if not provided
    if [ -z "$DB_NAME" ]; then
        export DB_NAME="defai"
        echo -e "${YELLOW}Using default database name: defai${NC}"
    fi
    
    if [ -z "$DB_USER" ]; then
        export DB_USER="postgres"
        echo -e "${YELLOW}Using default database user: postgres${NC}"
    fi
    
    return 0
}

# Extract DB password from arguments if provided
if [ "$#" -ge 3 ]; then
    # If we have at least 3 arguments, the third one is the DB password
    export DB_PASSWORD="$3"
    echo -e "${GREEN}Using database password from command line argument.${NC}"
    # Remove the first three arguments (AWS credentials and DB password)
    shift 3
else
    # Get database credentials using the function
    get_db_credentials "$@"
    if [ $? -ne 0 ]; then
        exit 1
    fi
    
    # Shift arguments if we consumed the DB password
    if [ "$#" -gt 0 ] && [[ "$1" != -* ]]; then
        shift 1
    fi
fi

# Default command is 'up -d' if not provided
DOCKER_COMPOSE_CMD=${@:-"up -d"}

echo -e "${YELLOW}Running: docker compose $DOCKER_COMPOSE_CMD${NC}"

# Ensure .env file exists in the current directory
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Creating empty .env file to avoid Docker Compose errors${NC}"
    touch .env
fi

# Run docker-compose with the credentials in the environment
docker compose $DOCKER_COMPOSE_CMD

# Check if the command was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Docker containers started successfully with credentials.${NC}"
else
    echo -e "${RED}Failed to start Docker containers.${NC}"
    exit 1
fi

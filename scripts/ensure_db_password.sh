#!/bin/bash

# Script to ensure database password is correctly set
# This can be run before starting the application to verify credentials

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Checking database credentials...${NC}"

# Check if DB_PASSWORD is set in environment
if [ -z "$DB_PASSWORD" ]; then
    echo -e "${RED}Error: DB_PASSWORD is not set in environment${NC}"
    
    # Check if it's in .env file
    if [ -f ".env" ]; then
        DB_PASSWORD_IN_ENV=$(grep -E "^DB_PASSWORD=" .env | cut -d= -f2)
        if [ -n "$DB_PASSWORD_IN_ENV" ]; then
            echo -e "${YELLOW}Found DB_PASSWORD in .env file${NC}"
            export DB_PASSWORD="$DB_PASSWORD_IN_ENV"
        else
            echo -e "${RED}DB_PASSWORD not found in .env file${NC}"
        fi
    else
        echo -e "${YELLOW}.env file not found${NC}"
    fi
    
    # Try to get from AWS Secrets Manager if credentials are available
    if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ] && [ -n "$AWS_SECRET_NAME" ]; then
        echo -e "${YELLOW}Attempting to fetch database password from AWS Secrets Manager...${NC}"
        
        if [ -f "./scripts/verify_aws_secrets.py" ]; then
            # Run the script and capture the output
            SECRET_JSON=$(python3 ./scripts/verify_aws_secrets.py --secret-name "${AWS_SECRET_NAME:-defai/backend}" --region "${AWS_REGION:-us-east-1}" --json-output 2>/dev/null)
            
            # Check if we got valid JSON
            if [ $? -eq 0 ] && [ -n "$SECRET_JSON" ]; then
                # Extract database password from JSON
                DB_PASSWORD_FROM_AWS=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('DB_PASSWORD', ''))")
                
                if [ -n "$DB_PASSWORD_FROM_AWS" ]; then
                    export DB_PASSWORD="$DB_PASSWORD_FROM_AWS"
                    echo -e "${GREEN}Successfully retrieved DB_PASSWORD from AWS Secrets Manager${NC}"
                    
                    # Update .env file with the password
                    if [ -f ".env" ]; then
                        # Remove existing DB_PASSWORD line if it exists
                        sed -i '/^DB_PASSWORD=/d' .env
                        # Add the new password
                        echo "DB_PASSWORD=$DB_PASSWORD" >> .env
                        echo -e "${GREEN}Updated .env file with DB_PASSWORD${NC}"
                    else
                        # Create .env file with the password
                        echo "DB_PASSWORD=$DB_PASSWORD" > .env
                        echo -e "${GREEN}Created .env file with DB_PASSWORD${NC}"
                    fi
                else
                    echo -e "${RED}DB_PASSWORD not found in AWS Secrets Manager${NC}"
                fi
            else
                echo -e "${RED}Failed to retrieve secrets from AWS Secrets Manager${NC}"
            fi
        else
            echo -e "${RED}verify_aws_secrets.py script not found${NC}"
        fi
    fi
else
    echo -e "${GREEN}DB_PASSWORD is set in environment${NC}"
    
    # Update .env file with the password if it exists
    if [ -f ".env" ]; then
        # Check if DB_PASSWORD is already in .env
        if grep -q "^DB_PASSWORD=" .env; then
            # Update existing DB_PASSWORD
            sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PASSWORD/" .env
        else
            # Add DB_PASSWORD to .env
            echo "DB_PASSWORD=$DB_PASSWORD" >> .env
        fi
        echo -e "${GREEN}Updated .env file with DB_PASSWORD${NC}"
    else
        # Create .env file with the password
        echo "DB_PASSWORD=$DB_PASSWORD" > .env
        echo -e "${GREEN}Created .env file with DB_PASSWORD${NC}"
    fi
fi

# Final check
if [ -z "$DB_PASSWORD" ]; then
    echo -e "${RED}Failed to set DB_PASSWORD. Please provide it manually.${NC}"
    exit 1
else
    echo -e "${GREEN}DB_PASSWORD is now set correctly${NC}"
    echo -e "${YELLOW}You can now run docker compose up -d${NC}"
    exit 0
fi

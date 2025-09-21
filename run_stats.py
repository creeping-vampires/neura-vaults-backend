#!/usr/bin/env python
"""
Wrapper script to run fetch_platform_stats with appropriate database configuration.
This script automatically selects SQLite for development and PostgreSQL for production.

Usage:
  python run_stats.py [options]
  
Options:
  --env development|production  Specify environment (default: development)
  --verbose                     Show additional statistics
  --use-postgres                Force PostgreSQL usage even in development
"""
import os
import sys
import subprocess

# Parse arguments to check for environment flag
is_production = False
args_to_pass = []

i = 0
while i < len(sys.argv):
    if i > 0:  # Skip script name
        if sys.argv[i] == "--env" and i + 1 < len(sys.argv):
            if sys.argv[i + 1].lower() == "production":
                is_production = True
            # Still pass these arguments to the command
            args_to_pass.append(sys.argv[i])
            args_to_pass.append(sys.argv[i + 1])
            i += 2
            continue
        elif sys.argv[i].startswith("--env="):
            env_value = sys.argv[i].split("=")[1]
            if env_value.lower() == "production":
                is_production = True
            # Pass this argument to the command
            args_to_pass.append(sys.argv[i])
            i += 1
            continue
        args_to_pass.append(sys.argv[i])
    i += 1

# Check environment variable as well
if os.environ.get('DEFAI_ENV', '').lower() == 'production':
    is_production = True

# Set database configuration based on environment
if is_production:
    # For production, ensure SQLite is not used
    os.environ['USE_SQLITE'] = 'false'
    print("Running in PRODUCTION mode with PostgreSQL")
else:
    # For development, use SQLite
    os.environ['USE_SQLITE'] = 'true'
    print("Running in DEVELOPMENT mode with SQLite")

# Get the command to run
command = ['python', 'manage.py', 'fetch_platform_stats']

# Add any arguments passed to this script
if args_to_pass:
    command.extend(args_to_pass)

print(f"Running command: {' '.join(command)}")

# Run the command
result = subprocess.run(command)
sys.exit(result.returncode)

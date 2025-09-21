#!/usr/bin/env python3
"""
Script to migrate secrets from .env file to AWS Secrets Manager.
This script reads the .env file and creates a secret in AWS Secrets Manager.
"""

import argparse
import boto3
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import dotenv_values

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Migrate secrets from .env file to AWS Secrets Manager')
    parser.add_argument('--env-file', type=str, default='.env', help='Path to .env file')
    parser.add_argument('--env', choices=['dev', 'staging', 'production'], help='Environment to use (.env.{env} file)')
    parser.add_argument('--secret-name', type=str, default='defai/backend', help='Name of the secret in AWS Secrets Manager')
    parser.add_argument('--region', type=str, default='us-east-1', help='AWS region')
    parser.add_argument('--description', type=str, default='DefAI Backend Secrets', help='Description of the secret')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (do not create secret)')
    parser.add_argument('--force', action='store_true', help='Force update even if the secret exists')
    parser.add_argument('--access-key', type=str, help='AWS access key ID')
    parser.add_argument('--secret-key', type=str, help='AWS secret access key')
    parser.add_argument('--session-token', type=str, help='AWS session token (optional)')
    return parser.parse_args()

def read_env_file(env_file_path):
    """Read environment variables from .env file."""
    if not os.path.exists(env_file_path):
        logger.error(f"Environment file not found: {env_file_path}")
        sys.exit(1)
    
    logger.info(f"Reading environment variables from {env_file_path}")
    return dotenv_values(env_file_path)

def create_or_update_aws_secret(secret_name, secret_value, region, description, dry_run=False, force=False, access_key=None, secret_key=None, session_token=None):
    """Create or update a secret in AWS Secrets Manager."""
    if dry_run:
        logger.info(f"DRY RUN: Would create/update secret '{secret_name}' in region '{region}'")
        logger.info(f"Secret value would contain {len(secret_value)} keys")
        return
    
    try:
        # Create a Secrets Manager client with provided credentials if available
        session_kwargs = {'region_name': region}
        if access_key and secret_key:
            logger.info("Using provided AWS credentials")
            session_kwargs['aws_access_key_id'] = access_key
            session_kwargs['aws_secret_access_key'] = secret_key
            if session_token:
                session_kwargs['aws_session_token'] = session_token
        else:
            logger.info("Using default AWS credentials from environment or config file")
        
        session = boto3.session.Session()
        client = session.client(service_name='secretsmanager', **session_kwargs)
        
        # Check if the secret exists
        try:
            # Try to describe the secret to see if it exists
            secret_info = client.describe_secret(SecretId=secret_name)
            
            # Check if the secret is scheduled for deletion
            if 'DeletedDate' in secret_info:
                logger.info(f"Secret '{secret_name}' is scheduled for deletion, restoring it")
                client.restore_secret(SecretId=secret_name)
                logger.info(f"Secret '{secret_name}' has been restored")
            
            # If force is True, use put_secret_value instead of delete and recreate
            # This avoids the issue with secrets scheduled for deletion
            if force:
                logger.info(f"Force flag is set, overwriting secret value for '{secret_name}'")
                response = client.put_secret_value(
                    SecretId=secret_name,
                    SecretString=json.dumps(secret_value)
                )
                # Also update the description
                client.update_secret_version_stage(
                    SecretId=secret_name,
                    VersionStage='AWSCURRENT',
                    MoveToVersionId=response['VersionId']
                )
                client.update_secret(
                    SecretId=secret_name,
                    Description=description
                )
                logger.info(f"Secret value forcefully updated: {secret_name}")
                return secret_info['ARN']
            
            logger.info(f"Secret '{secret_name}' already exists, updating it")
            # Update the secret
            response = client.update_secret(
                SecretId=secret_name,
                Description=description,
                SecretString=json.dumps(secret_value)
            )
            logger.info(f"Secret updated successfully: {response['ARN']}")
            return response['ARN']
            
        except client.exceptions.ResourceNotFoundException:
            # Secret doesn't exist, create it
            logger.info(f"Secret '{secret_name}' doesn't exist, creating it")
            response = client.create_secret(
                Name=secret_name,
                Description=description,
                SecretString=json.dumps(secret_value)
            )
            logger.info(f"Secret created successfully: {response['ARN']}")
            return response['ARN']
        
    except Exception as e:
        logger.error(f"Error managing secret: {str(e)}")
        # Print more detailed error information for debugging
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error details: {str(e)}")
        sys.exit(1)

def main():
    """Main function."""
    args = parse_args()
    
    # Determine which env file to use
    env_file_path = args.env_file
    if args.env:
        env_file_path = f".env.{args.env}"
        logger.info(f"Using environment file for {args.env} environment: {env_file_path}")
    
    # Read environment variables from .env file
    env_vars = read_env_file(env_file_path)
    
    # Filter out empty values
    filtered_env_vars = {k: v for k, v in env_vars.items() if v is not None and v != ""}
    
    logger.info(f"Found {len(filtered_env_vars)} environment variables")
    
    # Create or update secret in AWS Secrets Manager
    create_or_update_aws_secret(
        args.secret_name,
        filtered_env_vars,
        args.region,
        args.description,
        args.dry_run,
        args.force,
        args.access_key,
        args.secret_key,
        args.session_token
    )
    
    logger.info("Done!")

if __name__ == "__main__":
    main()

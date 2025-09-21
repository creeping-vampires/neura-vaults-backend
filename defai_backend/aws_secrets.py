"""
AWS Secrets Manager integration for DefAI backend.
This module provides utilities to fetch secrets from AWS Secrets Manager.
"""
import json
import logging
import os
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Cache for secrets to avoid repeated API calls
_secrets_cache = {}


def get_secret(secret_name: str, region_name: str = "us-east-1") -> Optional[Dict[str, Any]]:
    """
    Retrieve a secret from AWS Secrets Manager.
    
    Args:
        secret_name: The name or ARN of the secret to retrieve
        region_name: AWS region where the secret is stored
        
    Returns:
        Dictionary containing the secret key/value pairs or None if retrieval fails
    """
    # Check if secret is already in cache
    if secret_name in _secrets_cache:
        return _secrets_cache[secret_name]
    
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        logger.error(f"Failed to retrieve secret {secret_name}: {str(e)}")
        # For development/testing fallback to environment variables
        setup_mode = os.environ.get('SETUP', 'local').lower()
        if setup_mode == 'local' or os.environ.get('ENVIRONMENT') == 'development':
            logger.warning(f"Using environment variables as fallback in {setup_mode} mode")
            return None
        raise e
    else:
        # Decrypts secret using the associated KMS key
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            secret_dict = json.loads(secret)
            # Cache the secret
            _secrets_cache[secret_name] = secret_dict
            return secret_dict
        else:
            # Binary secrets not supported in this implementation
            logger.error(f"Secret {secret_name} is binary and not supported")
            return None


def load_secrets_to_env(secret_name: str, region_name: str = "us-east-1") -> bool:
    """
    Load secrets from AWS Secrets Manager into environment variables.
    
    Args:
        secret_name: The name or ARN of the secret to retrieve
        region_name: AWS region where the secret is stored
        
    Returns:
        True if secrets were loaded successfully, False otherwise
    """
    secrets = get_secret(secret_name, region_name)
    if not secrets:
        logger.warning(f"No secrets found for {secret_name}")
        return False
    
    # Set environment variables
    for key, value in secrets.items():
        if value is not None:
            os.environ[key] = str(value)
    
    logger.info(f"Loaded {len(secrets)} secrets from AWS Secrets Manager")
    return True

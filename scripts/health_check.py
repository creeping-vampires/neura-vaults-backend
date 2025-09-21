#!/usr/bin/env python
"""
Health Check Script for Nura Vault Backend

This script performs a basic health check on the Nura Vault backend API
by making a request to the health endpoint and verifying the response.
It can be used in CI/CD pipelines or monitoring systems to ensure the
application is running correctly.

Usage:
    python health_check.py [--url URL] [--timeout SECONDS]

Options:
    --url URL       The health check URL (default: http://localhost:8000/api/health/)
    --timeout SECS  Request timeout in seconds (default: 10)

Exit codes:
    0 - API is healthy
    1 - API is unhealthy or unreachable
"""

import argparse
import json
import sys
import time
import requests


def check_health(url, timeout):
    """
    Check if the API is healthy by making a request to the health endpoint.
    
    Args:
        url (str): The health check URL
        timeout (int): Request timeout in seconds
        
    Returns:
        tuple: (is_healthy, response_data)
    """
    try:
        start_time = time.time()
        response = requests.get(url, timeout=timeout)
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'healthy':
                return True, {
                    'status': data.get('status'),
                    'version': data.get('version'),
                    'environment': data.get('environment'),
                    'response_time': f"{response_time:.3f}s",
                    'database_status': data.get('database', {}).get('status'),
                }
        
        return False, {
            'status': 'unhealthy',
            'status_code': response.status_code,
            'response_time': f"{response_time:.3f}s",
            'message': 'API returned non-healthy status'
        }
    
    except requests.exceptions.RequestException as e:
        return False, {
            'status': 'unreachable',
            'message': str(e)
        }


def main():
    parser = argparse.ArgumentParser(description='Health check for Nura Vault Backend API')
    parser.add_argument('--url', default='http://localhost:8000/api/health/',
                        help='Health check URL (default: http://localhost:8000/api/health/)')
    parser.add_argument('--timeout', type=int, default=10,
                        help='Request timeout in seconds (default: 10)')
    
    args = parser.parse_args()
    
    print(f"Checking health of {args.url}...")
    is_healthy, data = check_health(args.url, args.timeout)
    
    print(json.dumps(data, indent=2))
    
    if is_healthy:
        print("✅ API is healthy")
        sys.exit(0)
    else:
        print("❌ API is unhealthy or unreachable")
        sys.exit(1)


if __name__ == '__main__':
    main()

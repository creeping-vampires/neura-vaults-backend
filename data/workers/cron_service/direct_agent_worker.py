#!/usr/bin/env python
"""
Direct Agent Worker - Bypasses Django management commands entirely
Directly imports and runs AgentRunner for maximum Docker/Railway compatibility
"""
import os
import sys
import django
import time
import traceback
from pathlib import Path
from datetime import datetime

# Set environment variables before Django setup
os.environ['USE_SQLITE'] = 'false'

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

def log_with_timestamp(message):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def check_environment_variables():
    """Check required environment variables"""
    log_with_timestamp("🔍 Checking environment variables...")
    
    required_vars = [
        'OPENAI_API_KEY',
        'RPC_URL',
        'YIELD_ALLOCATOR_VAULT_ADDRESS',
        'AI_AGENT_ADDRESS'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
            log_with_timestamp(f"❌ Missing required environment variable: {var}")
        else:
            # Mask sensitive values
            if var == 'OPENAI_API_KEY':
                value = f"{os.environ.get(var)[:5]}...{os.environ.get(var)[-4:]}"
            elif var == 'RPC_URL':
                value = f"{os.environ.get(var)[:15]}...{os.environ.get(var)[-10:]}"
            else:
                value = os.environ.get(var)
            log_with_timestamp(f"✅ {var}: {value}")
    
    # Log other useful environment variables
    log_with_timestamp(f"📊 DJANGO_SETTINGS_MODULE: {os.environ.get('DJANGO_SETTINGS_MODULE')}")
    log_with_timestamp(f"📊 DATABASE_URL: {os.environ.get('DATABASE_URL', 'Not set, using SQLite')}")
    log_with_timestamp(f"📊 PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")
    
    return len(missing_vars) == 0

def check_database_connectivity():
    """Check database connectivity"""
    log_with_timestamp("🔍 Checking database connectivity...")
    try:
        from django.db import connection
        connection.ensure_connection()
        log_with_timestamp("✅ Database connection successful")
        return True
    except Exception as e:
        log_with_timestamp(f"❌ Database connection failed: {str(e)}")
        traceback.print_exc()
        return False

def main():
    """Run the agent worker directly"""
    start_time = time.time()
    log_with_timestamp("🤖 Starting Direct Agent Worker...")
    log_with_timestamp(f"📍 Project root: {project_root}")
    log_with_timestamp(f"🐍 Python path: {sys.path}")
    log_with_timestamp(f"🐍 Python version: {sys.version}")
    
    # Setup Django
    try:
        log_with_timestamp("🔧 Setting up Django...")
        django.setup()
        log_with_timestamp("✅ Django setup complete")
    except Exception as e:
        log_with_timestamp(f"❌ Django setup failed: {str(e)}")
        traceback.print_exc()
        return 1
    
    # Check environment variables
    if not check_environment_variables():
        log_with_timestamp("❌ Environment validation failed")
        return 1
    
    # Check database connectivity
    if not check_database_connectivity():
        log_with_timestamp("❌ Database connectivity check failed")
        return 1
    
    try:
        # Import required modules
        log_with_timestamp("📚 Importing required modules...")
        
        try:
            from data.workers.agent_worker import AgentRunner
            log_with_timestamp("✅ Successfully imported AgentRunner")
        except Exception as e:
            log_with_timestamp(f"❌ Failed to import AgentRunner: {str(e)}")
            traceback.print_exc()
            return 1
        
        # Check if we can import other key dependencies
        try:
            from data.crew.crew import Crew
            log_with_timestamp("✅ Successfully imported Crew")
        except Exception as e:
            log_with_timestamp(f"❌ Failed to import Crew: {str(e)}")
            traceback.print_exc()
        
        try:
            from data.crew.tools.liquidity_pool_tools import execute_yield_allocation
            log_with_timestamp("✅ Successfully imported execute_yield_allocation")
        except Exception as e:
            log_with_timestamp(f"❌ Failed to import execute_yield_allocation: {str(e)}")
            traceback.print_exc()
        
        try:
            log_with_timestamp("✅ Successfully imported data models")
        except Exception as e:
            log_with_timestamp(f"❌ Failed to import data models: {str(e)}")
            traceback.print_exc()
        
        # Create and run AgentRunner
        log_with_timestamp("🚀 Creating AgentRunner instance...")
        try:
            runner = AgentRunner()
            log_with_timestamp("✅ AgentRunner instance created successfully")
        except Exception as e:
            log_with_timestamp(f"❌ Failed to create AgentRunner instance: {str(e)}")
            traceback.print_exc()
            return 1
        
        log_with_timestamp("🎯 Running agent...")
        try:
            success = runner.run()
            
            if success:
                log_with_timestamp("✅ Agent worker completed successfully")
                elapsed_time = time.time() - start_time
                log_with_timestamp(f"⏱️ Total execution time: {elapsed_time:.2f} seconds")
                return 0
            else:
                log_with_timestamp("❌ Agent worker completed with issues")
                elapsed_time = time.time() - start_time
                log_with_timestamp(f"⏱️ Total execution time: {elapsed_time:.2f} seconds")
                return 1
        except Exception as e:
            log_with_timestamp(f"❌ Agent worker run failed: {str(e)}")
            traceback.print_exc()
            return 1
            
    except Exception as e:
        log_with_timestamp(f"❌ Unexpected error: {str(e)}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    log_with_timestamp(f"🏁 Agent worker exiting with code: {exit_code}")
    sys.exit(exit_code)

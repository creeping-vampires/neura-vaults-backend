# Nura Vault Backend

A robust Django-based backend service for DeFi yield optimization and allocation, providing automated yield monitoring, claiming, and rebalancing across multiple protocols.

## Overview

Nura Vault Backend is a comprehensive Django application that manages yield optimization strategies across multiple DeFi protocols. The system automates the monitoring, claiming, and rebalancing of yield to maximize returns while minimizing gas costs. It provides a complete API for tracking yield performance, vault prices, and allocation decisions.

## Core Features

- **Automated Yield Monitoring**: Continuously tracks yield across multiple DeFi protocols
- **Yield Claiming & Reinvestment**: Automatically claims and reinvests yield when profitable
- **Intelligent Rebalancing**: Optimizes capital allocation across protocols based on APR/APY
- **Vault Price Tracking**: Calculates and stores share price and total asset values
- **APR/APY Calculation**: Implements time-weighted return calculations for accurate yield metrics
- **Comprehensive API**: RESTful endpoints for monitoring all system activities
- **Agent-Agnostic Architecture**: Supports both AI-agent driven and direct execution modes
- **Transaction Tracking**: Complete audit trail of all blockchain transactions
- **Performance Analytics**: Detailed metrics and reporting on yield performance

## Tech Stack

- **Framework**: Django with Django REST Framework
- **Database**: PostgreSQL
- **Blockchain Interaction**: Web3.py
- **API Documentation**: DRF Spectacular (OpenAPI)
- **Containerization**: Docker & Docker Compose
- **Deployment**: Railway/AWS compatible
- **Monitoring**: Custom metrics and logging system

## System Architecture

### Core Components

The system is built around several key components that work together:

1. **Yield Monitor Worker**: Monitors and claims yield from various DeFi protocols
2. **APY Monitor Worker**: Tracks and calculates APR/APY for different protocols
3. **Simple Agent Worker**: Executes yield allocation strategies without AI dependencies
4. **Web API**: Provides endpoints for monitoring and controlling the system
5. **Database**: Stores all transaction data, metrics, and system state

### Worker Services

The system runs multiple worker services to handle different aspects of yield optimization:

- **yield-monitor**: Monitors yield across protocols, claims when profitable, and reinvests
- **apy-monitor**: Calculates and tracks APR/APY for different protocols
- **simple-agent-worker**: Executes allocation strategies based on configured parameters

### Database Models

Key models in the system include:

- **YieldMonitorRun**: Tracks each yield monitoring cycle and its results
- **YieldMonitorPoolSnapshot**: Records pool-specific data for each monitoring run
- **YieldMonitorTransaction**: Stores details of all blockchain transactions
- **VaultPrice**: Tracks vault share price and total assets over time
- **PoolAPR**: Stores APR/APY calculations for different pools
- **RebalancingTrade**: Records all rebalancing transactions with detailed metadata

## API Endpoints

The system provides comprehensive API endpoints for monitoring and controlling the yield optimization process:

### Yield Monitoring

- `GET /api/yield-monitor/status/`: Current status of the yield monitor
- `GET /api/yield-monitor/history/`: Historical yield monitoring runs
- `GET /api/yield-monitor/pool-performance/`: Performance metrics for individual pools
- `GET /api/yield-monitor/daily-metrics/`: Aggregated daily performance metrics

### Vault Price

- `GET /api/vault/price/`: Latest vault price data
- `GET /api/vault/price-chart/`: Historical price data for charts with filtering options

### Rebalancing

- `GET /api/rebalancing-trades/`: Complete history of rebalancing trades with filtering options

### System Health

- `GET /api/health/`: System health check endpoint
- `GET /api/agent-thoughts/`: Latest agent thoughts and decision-making process

### API Documentation

- `GET /api/docs/`: Swagger UI documentation
- `GET /api/redoc/`: ReDoc documentation
- `GET /api/schema/`: OpenAPI schema

## Installation

### Prerequisites

- Python 3.9+
- PostgreSQL 14+
- Docker and Docker Compose (for containerized deployment)
- Ethereum RPC endpoint with archive node capabilities

### Environment Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd neura-vault-backend
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -e .
   ```

3. Create a `.env` file based on `.env.example`:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. Run database migrations:
   ```bash
   python manage.py migrate
   ```

### Configuration

Key environment variables to configure:

- **Database Settings**:
  - `DB_NAME`: PostgreSQL database name
  - `DB_USER`: Database username
  - `DB_PASSWORD`: Database password
  - `DB_HOST`: Database host (use "db" for Docker Compose)

- **Blockchain Settings**:
  - `RPC_URL`: Ethereum RPC endpoint URL
  - `VAULT_ADDRESS`: NuraVault contract address
  - `PRIVATE_KEY`: Private key for transaction signing (secure with AWS Secrets Manager)

- **Worker Settings**:
  - `YIELD_THRESHOLD`: Minimum yield percentage to trigger claiming
  - `MIN_CLAIM_AMOUNT_USD`: Minimum USD value to claim
  - `MAX_GAS_COST_USD`: Maximum gas cost for profitable transactions
  - `AGENT_WORKER_INTERVAL_SECONDS`: Worker execution interval

### Running with Docker

1. Build and start all services:
   ```bash
   docker-compose up -d
   ```

2. Monitor logs:
   ```bash
   docker-compose logs -f
   ```

### Running Locally

1. Start the web server:
   ```bash
   ./run-dev.sh
   ```

2. Run the yield monitor worker:
   ```bash
   ./scripts/run-yield-monitor-worker.sh
   ```

3. Run the APY monitor worker:
   ```bash
   ./scripts/run-apy-monitor-worker.sh
   ```

## Development

### Project Structure

- `data/`: Main application directory
  - `models.py`: Database models
  - `views/`: API views and endpoints
  - `serializers/`: REST framework serializers
  - `crew/`: Agent implementation and tools
    - `tools/`: Blockchain interaction tools
  - `migrations/`: Database migrations

- `defai_backend/`: Django project settings
  - `settings.py`: Application settings
  - `urls.py`: URL routing configuration
  - `aws_secrets.py`: AWS Secrets Manager integration

- `scripts/`: Utility scripts and worker runners
  - `run-yield-monitor-worker.sh`: Yield monitor worker script
  - `run-apy-monitor-worker.sh`: APY monitor worker script
  - `run-simple-agent-worker.sh`: Simple agent worker script

### Adding New Protocols

To add support for a new DeFi protocol:

1. Create protocol-specific adapter in `data/crew/tools/`
2. Implement the required interface methods:
   - `get_protocol_balance()`
   - `get_protocol_yield()`
   - `claim_yield()`
   - `calculate_apr_apy()`
3. Register the protocol in the yield monitor configuration
4. Update tests to cover the new protocol

### Database Migrations

When modifying models, create and apply migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Monitoring and Maintenance

### Logs

Worker logs are stored in the `logs/` directory with the following files:

- `yield_monitor.log`: Yield monitor worker logs
- `apy_monitor.log`: APY monitor worker logs
- `simple_agent.log`: Simple agent worker logs

### Database Backups

Regular database backups are recommended:

```bash
pg_dump -U $DB_USER -d $DB_NAME > backup_$(date +%Y%m%d).sql
```

### Performance Tuning

For optimal performance:

1. Adjust worker intervals based on gas prices and yield frequency
2. Configure appropriate thresholds for yield claiming
3. Monitor database query performance and add indexes as needed
4. Consider scaling worker instances for high-volume deployments

## Security Considerations

- Private keys should be stored securely using AWS Secrets Manager
- API endpoints should be protected with appropriate authentication
- Regular security audits of smart contract interactions
- Monitoring for unusual transaction patterns or gas costs

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

[Specify your license information here]
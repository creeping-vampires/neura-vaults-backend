# Cron Jobs and Scheduled Tasks

This directory contains scripts for scheduled tasks that need to run periodically.

## Setting Up the Portfolio Snapshots Cron Job

The `portfolio_snapshots.sh` script creates snapshots of agent portfolio values every time it runs. These snapshots are used to calculate 24-hour PNL (Profit and Loss) for agents.

### To set up the cron job to run every 15 minutes:

1. Open your crontab configuration:

```
crontab -e
```

2. Add the following line to run the script every 15 minutes:

```
*/15 * * * * /Users/aamir/Desktop/3poch/hype/def-ai/defai-backend/cron/portfolio_snapshots.sh
```

3. Save and exit the editor.

### For production environments:

Make sure the cron job is set up on the production server with the correct path to the script. You may need to adjust paths and environment variables for your production setup.

## Verifying the Cron Job

You can check if the cron job is running by looking at the log file:

```
cat /Users/aamir/Desktop/3poch/hype/def-ai/defai-backend/cron/portfolio_snapshots.log
```

The log should show timestamps of when the script was executed.

## Manual Execution

You can also run the script manually to create snapshots immediately:

```
/Users/aamir/Desktop/3poch/hype/def-ai/defai-backend/cron/portfolio_snapshots.sh
```

Or run the Django management command directly:

```
cd /Users/aamir/Desktop/3poch/hype/def-ai/defai-backend
python manage.py create_portfolio_snapshots
```

## Managing Credit Requests

The credit request management has been split into two scripts:

1. `view_credit_requests.py` - For viewing and listing pending credit requests
2. `approve_credit_requests.py` - For approving specific or all pending credit requests

### Viewing Credit Requests

The `view_credit_requests.py` script displays all credit requests with their Privy IDs and Twitter handles.

#### Running in Docker:

```bash
# View all credit requests
docker-compose exec web python cron/view_credit_requests.py

# View only pending requests
docker-compose exec web python cron/view_credit_requests.py --status pending

# View only approved requests
docker-compose exec web python cron/view_credit_requests.py --status approved
```

#### Running Locally:

```bash
# Activate the virtual environment
source .venv/bin/activate

# View credit requests
python cron/view_credit_requests.py --status pending
```

### Approving Credit Requests

The `approve_credit_requests.py` script approves pending credit requests based on specified criteria.

#### Running in Docker:

```bash
# View pending credit requests
docker-compose exec web python cron/view_credit_requests.py --status pending

# Approve a specific Twitter handle
docker-compose exec web python cron/approve_credit_requests.py --twitter username123

# Approve all pending requests
docker-compose exec web python cron/approve_credit_requests.py --all
```

#### Running Locally:

```bash
# Activate the virtual environment
source .venv/bin/activate

# Approve specific requests
python cron/approve_credit_requests.py --twitter username123
```

### Scheduling Credit Request Processing

To set up a cron job to process credit requests daily:

1. Open your crontab configuration:

```
crontab -e
```

2. Add the following lines:

```
# View pending requests daily at 9 AM
0 9 * * * docker-compose -f /path/to/docker-compose.yml exec -T web python cron/view_credit_requests.py --status pending >> /path/to/logs/credit_requests_view.log 2>&1

# Approve requests from the approved list daily at 10 AM
0 10 * * * docker-compose -f /path/to/docker-compose.yml exec -T web python cron/approve_credit_requests.py >> /path/to/logs/credit_requests_approve.log 2>&1
```

3. Save and exit the editor.

Note: Replace `/path/to/docker-compose.yml` with the actual path to your docker-compose.yml file and `/path/to/logs/` with your desired log directory.

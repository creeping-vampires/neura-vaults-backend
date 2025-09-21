# Admin Documentation

## User Role Management

The system supports three user roles:
- **USER**: Regular user with basic permissions
- **KOL**: Key Opinion Leader with additional permissions to create invite codes
- **ADMIN**: Administrator with full system access

### Managing User Roles

You can assign or remove roles using the `assign_user_role` management command:

#### Local Environment

```bash
# Assign ADMIN role to a user
python manage.py assign_user_role <privy_address> --role admin

# Assign KOL role to a user
python manage.py assign_user_role <privy_address> --role kol

# Remove a role from a user
python manage.py assign_user_role <privy_address> --role admin --remove
```

#### Docker Environment

```bash
# Assign ADMIN role to a user
docker-compose exec web python manage.py assign_user_role <privy_address> --role admin

# Assign KOL role to a user
docker-compose exec web python manage.py assign_user_role <privy_address> --role kol

# Remove a role from a user
docker-compose exec web python manage.py assign_user_role <privy_address> --role admin --remove
```

## Invite Code System

Invite codes can be created by KOL or ADMIN users. They provide credits to users who redeem them.

### KOL Daily Invite Code Limits

KOL users have a daily limit on how many invite codes they can create:

- Default daily limit: 5 invite codes per day
- This limit can be configured via the `KOL_DAILY_INVITE_LIMIT` environment variable
- The limit resets at midnight in the server's local timezone
- Admin users do not have a daily limit

### Creating Invite Codes

Use the `create_invite_code` management command to generate invite codes:

#### Local Environment

```bash
# Create a basic invite code (uses default credits based on user's role)
python manage.py create_invite_code <privy_address>

# Create an invite code with custom credits
python manage.py create_invite_code <privy_address> --credits 20

# Create an invite code that assigns KOL role (admin only)
python manage.py create_invite_code <privy_address> --assign-kol

# Create an invite code with custom expiration (days)
python manage.py create_invite_code <privy_address> --expires 60

# Create an invite code with a specific code string
python manage.py create_invite_code <privy_address> --code SPECIALCODE123
```

#### Docker Environment

```bash
# Create a basic invite code (uses default credits based on user's role)
docker-compose exec web python manage.py create_invite_code <privy_address>

# Create an invite code with custom credits
docker-compose exec web python manage.py create_invite_code <privy_address> --credits 20

# Create an invite code that assigns KOL role (admin only)
docker-compose exec web python manage.py create_invite_code <privy_address> --assign-kol

# Create an invite code with custom expiration (days)
docker-compose exec web python manage.py create_invite_code <privy_address> --expires 60

# Create an invite code with a specific code string
docker-compose exec web python manage.py create_invite_code <privy_address> --code SPECIALCODE123
```

### Invite Code Business Rules

- KOL users can create invite codes with fixed credits (from `KOL_INVITE_CREDITS` setting)
- Admin users can create invite codes with custom credits and KOL role assignment
- Invite codes expire once used
- Invite codes can assign KOL role if created by an admin with `assign_kol_role=True`

### Environment Variables

- `KOL_INVITE_CREDITS`: Default credits for KOL-generated invite codes (default: 5)
- `ADMIN_INVITE_CREDITS`: Default credits for admin-generated invite codes (default: 10)
- `KOL_DAILY_INVITE_LIMIT`: Daily limit for KOL users to create invite codes (default: 5)

## Platform Statistics

Use the following commands to view platform statistics including total trades, volume, agents, and AUM.

### Using the Wrapper Script (Recommended)

We've created a wrapper script that automatically handles database configuration based on environment:

```bash
# Run in development mode (uses SQLite)
python run_stats.py --verbose

# Run in production mode (uses PostgreSQL)
python run_stats.py --env production --verbose

# The script passes all arguments to the underlying command
python run_stats.py --verbose --use-postgres
```

### Development Environment

```bash
# Run the platform statistics command (uses development environment by default)
# In development mode, SQLite is used automatically
python manage.py fetch_platform_stats

# Run with verbose output for additional statistics
python manage.py fetch_platform_stats --verbose

# Force using PostgreSQL database even in development
python manage.py fetch_platform_stats --use-postgres
```

### Production Environment

```bash
# Run the command with production environment
# In production mode, PostgreSQL is used by default
python manage.py fetch_platform_stats --env production

# Or set the environment variable
export DEFAI_ENV=production
python manage.py fetch_platform_stats
```

### Docker Environment

```bash
# Run the command on the Docker container (development environment)
docker-compose exec web python manage.py fetch_platform_stats

# Run the command on the Docker container (production environment)
docker-compose exec web python manage.py fetch_platform_stats --env production

# Force using PostgreSQL in development environment
docker-compose exec web python manage.py fetch_platform_stats --use-postgres

# Or on a named container
docker exec -it defai-backend python manage.py fetch_platform_stats --env production
```

### Database Configuration

The command will automatically select the appropriate database based on the environment:

1. In `development` environment: SQLite is used by default
2. In `production` environment: PostgreSQL is used by default
3. Use `--use-postgres` to force PostgreSQL usage in development environment

### Remote Database Connection

To run the command against a remote production database:

1. Update your `.env` file with production database credentials:

```
DB_NAME=production_db_name
DB_USER=production_db_user
DB_PASSWORD=production_db_password
DB_HOST=production_db_host
DB_PORT=5432
USE_SQLITE=false
```

2. Then run the command as described above.

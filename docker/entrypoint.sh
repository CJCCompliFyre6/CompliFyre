#!/bin/sh

# This script ensures the PostgreSQL database is ready before running Flask migrations
# and starting the Gunicorn application server.

# Use 'nc -z' (netcat) to check if the database host 'db' is listening on port '5432'.
# This loop will continuously check until the port is open.
echo "Waiting for PostgreSQL to be ready..."
while ! nc -z db 5432; do
  sleep 0.5 # Wait for half a second before trying again
done
echo "PostgreSQL is now ready!"

# Initialize Flask-Migrate if the 'migrations' directory doesn't exist
# This is usually done only once for a fresh project
if [ ! -d "/app/migrations" ]; then
    echo "Initializing Flask-Migrate database migrations..."
    flask db init
fi

# Create migration scripts based on model changes (if any)
# This will generate new migration files if your models have changed since the last migration
echo "Running Flask-Migrate 'migrate' command..."
flask db migrate

# Apply all pending migrations to the database
# This updates your database schema to the latest version
echo "Running Flask-Migrate 'upgrade' command..."
flask db upgrade

# Finally, start the Gunicorn application server.
# The 'exec' command replaces the current shell process with the Gunicorn process,
# which is a standard practice for entrypoint scripts in Docker.
echo "Starting Gunicorn application server..."
exec gunicorn --workers=2 --timeout=600 --bind "0.0.0.0:80" "run:app"

#!/bin/bash
set -e

# Start the API in the background.
# We delay slightly to allow systemd (which we exec below) to initialize.
(
    echo "Waiting for systemd to initialize..."
    sleep 5
    echo "Starting Warppool API..."
    cd /app
    exec /usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
) &

# Execute systemd as PID 1 to manage other services (usque, etc.)
exec /sbin/init

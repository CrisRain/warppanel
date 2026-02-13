#!/bin/bash
set -e

# Port defaults (configurable via docker env)
export PANEL_PORT="${PANEL_PORT:-8000}"
export SOCKS5_PORT="${SOCKS5_PORT:-1080}"


# Start DBus (required for warp-svc)
mkdir -p /run/dbus
if [ -f /run/dbus/pid ]; then
  rm /run/dbus/pid
fi
dbus-daemon --config-file=/usr/share/dbus-1/system.conf --print-address --fork

# Create log directory and file for warppool-api
mkdir -p /var/log/supervisor
touch /var/log/warppool-api.log

# Tail the log in background so docker logs can see it
tail -f /var/log/warppool-api.log &

echo "Starting WarpPanel (Panel: ${PANEL_PORT}, SOCKS5: ${SOCKS5_PORT})"

# Start supervisor (which manages warppool-api, usque, socat)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf

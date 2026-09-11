#!/bin/sh
# Runs as root (container default user) before dropping privileges to the
# unprivileged "jarvis" user. Persistent volumes mounted at $JARVIS_DATA_ROOT
# (default /data) are typically owned by root regardless of the image's
# configured user, which causes the Python entrypoint to fail with
# "PermissionError: Permission denied: '/data'". Fix ownership/permissions
# here, then exec the real entrypoint as jarvis.
set -e

DATA_DIR="${JARVIS_DATA_ROOT:-/data}"
APP_UID=10001
APP_GID=10001
APP_USER=jarvis

mkdir -p "$DATA_DIR"
chown -R "${APP_UID}:${APP_GID}" "$DATA_DIR"
chmod 755 "$DATA_DIR"

if [ "$#" -eq 0 ]; then
    set -- python scripts/hosted_entrypoint.py
fi

if command -v gosu >/dev/null 2>&1; then
    exec gosu "$APP_USER" "$@"
elif command -v su-exec >/dev/null 2>&1; then
    exec su-exec "$APP_USER" "$@"
else
    exec su -s /bin/sh -c 'exec "$@"' "$APP_USER" -- "$@"
fi

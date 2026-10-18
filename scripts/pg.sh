#!/usr/bin/env bash
# Start a throwaway local PostgreSQL cluster for this project (port 54562).
set -euo pipefail
cd "$(dirname "$0")/.."
PGDATA=.pgdata PORT=${OLAP_PORT:-54562}
if [ ! -d "$PGDATA" ]; then
  initdb -D "$PGDATA" -U olap --auth=trust -E UTF8 --locale=C >/dev/null
fi
if ! pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
  pg_ctl -D "$PGDATA" -o "-p $PORT -k /tmp -c listen_addresses=127.0.0.1" -l .pgdata/server.log start >/dev/null
  sleep 1
fi
psql -h 127.0.0.1 -p "$PORT" -U olap -d postgres -tAc "select 1 from pg_database where datname='olap'" | grep -q 1 \
  || createdb -h 127.0.0.1 -p "$PORT" -U olap olap
echo "postgresql://olap@127.0.0.1:$PORT/olap"

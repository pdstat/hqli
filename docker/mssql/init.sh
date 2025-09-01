#!/usr/bin/env bash
set -euo pipefail

# Determine sqlcmd path (tools18 or legacy)
SQLCMD="/opt/mssql-tools18/bin/sqlcmd"
if [ ! -x "$SQLCMD" ]; then
  SQLCMD="/opt/mssql-tools/bin/sqlcmd"
fi

echo "Using sqlcmd at: $SQLCMD"

# Wait for SQL Server to accept connections
for i in {1..120}; do
  if "$SQLCMD" -S mssql -U sa -P "Str0ngPwd!" -C -Q "SELECT 1" >/dev/null 2>&1; then
    echo "SQL Server is ready (attempt $i)."
    break
  fi
  echo "Waiting for SQL Server... ($i)";
  sleep 2
done

# Run initialization script (idempotent)
"$SQLCMD" -S mssql -U sa -P "Str0ngPwd!" -C -i /scripts/init.sql

echo "Initialization completed."

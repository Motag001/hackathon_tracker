#!/usr/bin/env bash
# Applies the migrations to a throwaway Postgres database and runs the gate tests.
# Usage: DATABASE_URL=postgres://... supabase/tests/run.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
: "${DATABASE_URL:?set DATABASE_URL to an empty test database}"
psql_cmd=(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q)
"${psql_cmd[@]}" -f "$here/supabase_stub.sql"
for f in "$here"/../migrations/*.sql; do
    "${psql_cmd[@]}" -f "$f"
done
"${psql_cmd[@]}" -f "$here/test_gates.sql"

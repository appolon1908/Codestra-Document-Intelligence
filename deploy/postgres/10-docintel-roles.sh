#!/bin/sh
# Creates the non-superuser application role and the service-owned schema.
# RLS is only enforced for non-superusers, so the API must never connect as
# the bootstrap superuser.
set -eu
: "${DOCINTEL_APP_PASSWORD:?DOCINTEL_APP_PASSWORD must be set}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$DOCINTEL_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE docintel_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docintel_app')\gexec
CREATE SCHEMA IF NOT EXISTS docintel AUTHORIZATION docintel_app;
REVOKE ALL ON SCHEMA public FROM docintel_app;
ALTER ROLE docintel_app SET search_path = docintel;
SQL

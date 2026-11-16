#!/bin/sh
set -eu
# First initialization of the new Docker volume only. No access to host PostgreSQL.
psql --username "$POSTGRES_USER" --dbname postgres -v ON_ERROR_STOP=1 \
  --set=app_user="$DB_USER" --set=app_password="$DB_PASSWORD" --set=app_db="$DB_NAME" <<'SQL'
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE :"app_db" OWNER :"app_user";
SQL

#!/bin/sh
# Generates throwaway development secrets under ./secrets (gitignored).
set -eu
cd "$(dirname "$0")/.."
mkdir -p secrets
umask 077
gen() { [ -s "secrets/$1" ] || python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "secrets/$1"; }
gen pg_owner_password
gen pg_app_password
gen ocr_worker_token
gen inbound_service_tokens
gen document_hash_pepper
[ -s secrets/database_url ] || printf 'postgresql://docintel_app:%s@postgres:5432/docintel\n' "$(cat secrets/pg_app_password)" > secrets/database_url
chmod 644 secrets/*   # readable by the non-root container users; directory stays out of git
echo "dev secrets ready in ./secrets"

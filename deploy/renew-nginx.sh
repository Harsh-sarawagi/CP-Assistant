#!/bin/sh
set -eu
# Install this as a Certbot deploy hook after placing the project at this path.
cd /opt/cp-assistant
docker compose --env-file .env.production exec -T nginx nginx -t
docker compose --env-file .env.production exec -T nginx nginx -s reload

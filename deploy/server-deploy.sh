#!/usr/bin/env bash

set -euo pipefail

APP_DIR=${APP_DIR:-/opt/avangard-chat}
ENV_FILE="${APP_DIR}/.env.production"
COMPOSE_ARGS=(--env-file "$ENV_FILE" -f compose.yml -f compose.prod.yml)

required_vars=(
  APP_DOMAIN
  DOCKER_IMAGE
  GHCR_USERNAME
  GHCR_TOKEN
  LIVEKIT_URL
  JWT_SECRET_KEY
  REFRESH_TOKEN_SECRET_KEY
  MESSAGE_CURSOR_SECRET_KEY
  MESSAGE_ENCRYPTION_ACTIVE_KEY_ID
  MESSAGE_ENCRYPTION_KEYS
  TYPESENSE_API_KEY
  LIVEKIT_API_KEY
  LIVEKIT_API_SECRET
  S3_ACCESS_KEY
  S3_SECRET_KEY
  AI_API_KEY
  MONGODB_IMAGE
  DRAGONFLY_IMAGE
  LIVEKIT_IMAGE
  TYPESENSE_IMAGE
  S3_IMAGE
  PROMETHEUS_IMAGE
  GRAFANA_IMAGE
  CADDY_IMAGE
)

managed_vars=(
  APP_DOMAIN
  DOCKER_IMAGE
  LIVEKIT_URL
  JWT_SECRET_KEY
  REFRESH_TOKEN_SECRET_KEY
  MESSAGE_CURSOR_SECRET_KEY
  MESSAGE_ENCRYPTION_ACTIVE_KEY_ID
  MESSAGE_ENCRYPTION_KEYS
  TYPESENSE_API_KEY
  LIVEKIT_API_KEY
  LIVEKIT_API_SECRET
  S3_ACCESS_KEY
  S3_SECRET_KEY
  AI_API_KEY
  AI_BASE_URL
  AI_SUMMARY_MODEL
  AI_TRANSCRIPTION_MODEL
  TRUSTED_PROXY_CIDRS
  MONGODB_IMAGE
  DRAGONFLY_IMAGE
  LIVEKIT_IMAGE
  TYPESENSE_IMAGE
  S3_IMAGE
  PROMETHEUS_IMAGE
  GRAFANA_IMAGE
  CADDY_IMAGE
)

require_env() {
  local name=$1
  if [ -z "${!name:-}" ]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

escape_compose_value() {
  printf '%s' "$1" | sed 's/\$/$$/g'
}

append_env_var() {
  local file=$1
  local name=$2
  local value=$3

  printf '%s=%s\n' "$name" "$(escape_compose_value "$value")" >> "$file"
}

for name in "${required_vars[@]}"; do
  require_env "$name"
done

mkdir -p "$APP_DIR"

tmp_env=$(mktemp)
trap 'rm -f "$tmp_env"' EXIT

if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$tmp_env"
  for name in "${managed_vars[@]}"; do
    sed -i "/^${name}=.*/d" "$tmp_env"
  done
fi

for name in "${managed_vars[@]}"; do
  if [ -n "${!name:-}" ]; then
    append_env_var "$tmp_env" "$name" "${!name}"
  fi
done

mv "$tmp_env" "$ENV_FILE"
trap - EXIT

printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin

docker compose "${COMPOSE_ARGS[@]}" config >/dev/null
docker compose "${COMPOSE_ARGS[@]}" pull
docker compose "${COMPOSE_ARGS[@]}" up -d --remove-orphans --wait --wait-timeout 180
curl --fail --silent --show-error http://127.0.0.1:8000/health/ready >/dev/null
docker compose "${COMPOSE_ARGS[@]}" ps

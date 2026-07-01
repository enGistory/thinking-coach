#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'usage: %s /path/to/backup.dump\n' "$0" >&2
  exit 2
fi

backup_path="$1"
if [[ ! -f "${backup_path}" ]]; then
  printf 'backup file not found: %s\n' "${backup_path}" >&2
  exit 2
fi

checksum_path="${backup_path}.sha256"
if [[ ! -f "${checksum_path}" ]]; then
  if [[ "${RESTORE_ALLOW_MISSING_CHECKSUM:-}" != "1" ]]; then
    printf 'checksum sidecar not found: %s\n' "${checksum_path}" >&2
    printf 'set RESTORE_ALLOW_MISSING_CHECKSUM=1 only for explicitly approved legacy restore rehearsals\n' >&2
    exit 2
  fi
  printf 'warning: restoring without checksum sidecar: %s\n' "${backup_path}" >&2
else
  if ! command -v sha256sum >/dev/null 2>&1; then
    printf 'sha256sum is required to verify checksum: %s\n' "${checksum_path}" >&2
    exit 2
  fi

  expected_hash="$(awk 'NR == 1 {print $1}' "${checksum_path}")"
  if [[ ! "${expected_hash}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    printf 'invalid checksum sidecar: %s\n' "${checksum_path}" >&2
    exit 2
  fi

  actual_hash="$(sha256sum "${backup_path}" | awk '{print $1}')"
  if [[ "${actual_hash,,}" != "${expected_hash,,}" ]]; then
    printf '%s: FAILED\n' "${backup_path}" >&2
    exit 1
  fi
  printf '%s: OK\n' "${backup_path}"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${COMPOSE_FILE:-${repo_root}/infra/docker-compose.prod.yml}"
env_file="${COMPOSE_ENV_FILE:-${repo_root}/infra/env.production}"

require_env_file_without_bom() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    printf 'env file not found: %s\n' "${path}" >&2
    exit 2
  fi

  local prefix
  prefix="$(head -c 3 "${path}" || true)"
  if [[ "${prefix}" == $'\xef\xbb\xbf' ]]; then
    printf 'env file must be UTF-8 without BOM: %s\n' "${path}" >&2
    exit 2
  fi
}

strip_carriage_return() {
  local name="$1"
  if [[ -n "${!name:-}" ]]; then
    printf -v "${name}" '%s' "${!name//$'\r'/}"
  fi
}

require_env_file_without_bom "${env_file}"

set -a
# shellcheck disable=SC1090
. "${env_file}"
set +a

strip_carriage_return APP_ENV
strip_carriage_return RESTORE_ALLOW_PRODUCTION
strip_carriage_return POSTGRES_USER
strip_carriage_return POSTGRES_DB

if [[ "${APP_ENV:-}" == "production" && "${RESTORE_ALLOW_PRODUCTION:-}" != "1" ]]; then
  printf 'refusing to restore into APP_ENV=production without RESTORE_ALLOW_PRODUCTION=1\n' >&2
  exit 2
fi

docker compose --env-file "${env_file}" -f "${compose_file}" exec -T postgres \
  pg_restore --clean --if-exists --no-owner \
  -U "${POSTGRES_USER:?POSTGRES_USER is required}" \
  -d "${POSTGRES_DB:?POSTGRES_DB is required}" < "${backup_path}"

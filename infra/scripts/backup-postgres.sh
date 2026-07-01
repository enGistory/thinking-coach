#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${COMPOSE_FILE:-${repo_root}/infra/docker-compose.prod.yml}"
env_file="${COMPOSE_ENV_FILE:-${repo_root}/infra/env.production}"
backup_dir="${BACKUP_DIR:-${repo_root}/backups/postgres}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${backup_dir}/thinking-${timestamp}.dump"
temp_output="${output}.tmp"
checksum_output="${output}.sha256"
temp_checksum_output="${checksum_output}.tmp"
backup_file="$(basename "${output}")"
temp_backup_file="$(basename "${temp_output}")"
daily_keep="${BACKUP_RETENTION_DAILY:-7}"
weekly_keep="${BACKUP_RETENTION_WEEKLY:-4}"
final_dump_published=0

umask 077

cleanup_incomplete_backup() {
  rm -f -- "${temp_output}" "${temp_checksum_output}"
  if (( final_dump_published == 1 )) && [[ ! -f "${checksum_output}" ]]; then
    rm -f -- "${output}"
  fi
}

usage() {
  printf 'usage: %s [--prune-only]\n' "$0" >&2
}

require_minimum_integer() {
  local name="$1"
  local value="$2"
  local minimum="$3"

  if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( value < minimum )); then
    printf '%s must be an integer >= %s\n' "${name}" "${minimum}" >&2
    exit 2
  fi
}

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

is_timestamped_backup() {
  local filename="$1"
  if [[ ${#filename} -ne 30 ]]; then
    return 1
  fi
  if [[ "${filename:0:9}" != "thinking-" || "${filename:17:1}" != "T" || "${filename:24:6}" != "Z.dump" ]]; then
    return 1
  fi

  local digits="${filename:9:8}${filename:18:6}"
  case "${digits}" in
    *[!0-9]* | "")
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

prune_old_backups() {
  require_minimum_integer "BACKUP_RETENTION_DAILY" "${daily_keep}" 7
  require_minimum_integer "BACKUP_RETENTION_WEEKLY" "${weekly_keep}" 4

  mkdir -p "${backup_dir}"

  local -a backups=()
  local file
  while IFS= read -r file; do
    backups+=("${file}")
  done < <(find "${backup_dir}" -maxdepth 1 -type f -name 'thinking-*.dump' -exec basename {} \; | sort -r)

  local -A keep=()
  local index=0
  local older_index=0
  local weekly_count=0
  for file in "${backups[@]}"; do
    if ! is_timestamped_backup "${file}"; then
      keep["${file}"]=1
      continue
    fi

    index=$((index + 1))
    if (( index <= daily_keep )); then
      keep["${file}"]=1
      continue
    fi

    older_index=$((index - daily_keep))
    if (( (older_index - 1) % 7 == 0 )) && (( weekly_count < weekly_keep )); then
      keep["${file}"]=1
      weekly_count=$((weekly_count + 1))
    fi
  done

  for file in "${backups[@]}"; do
    if [[ -z "${keep[${file}]:-}" ]]; then
      rm -f -- "${backup_dir}/${file}" "${backup_dir}/${file}.sha256"
    fi
  done
}

if [[ $# -gt 1 ]]; then
  usage
  exit 2
fi

if [[ "${1:-}" == "--prune-only" ]]; then
  prune_old_backups
  exit 0
elif [[ $# -eq 1 ]]; then
  usage
  exit 2
fi

require_env_file_without_bom "${env_file}"
require_minimum_integer "BACKUP_RETENTION_DAILY" "${daily_keep}" 7
require_minimum_integer "BACKUP_RETENTION_WEEKLY" "${weekly_keep}" 4
if ! command -v sha256sum >/dev/null 2>&1; then
  printf 'sha256sum is required to write backup checksum sidecar\n' >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "${env_file}"
set +a

strip_carriage_return POSTGRES_USER
strip_carriage_return POSTGRES_DB

mkdir -p "${backup_dir}"
trap cleanup_incomplete_backup EXIT

docker compose --env-file "${env_file}" -f "${compose_file}" exec -T postgres \
  pg_dump -U "${POSTGRES_USER:?POSTGRES_USER is required}" \
  -d "${POSTGRES_DB:?POSTGRES_DB is required}" \
  -Fc > "${temp_output}"

(
  cd "${backup_dir}"
  checksum_hash="$(sha256sum "${temp_backup_file}" | awk '{print $1}')"
  printf '%s  %s\n' "${checksum_hash}" "${backup_file}" > "$(basename "${temp_checksum_output}")"
)

mv -- "${temp_output}" "${output}"
final_dump_published=1
mv -- "${temp_checksum_output}" "${checksum_output}"
trap - EXIT

prune_old_backups

printf '%s\n' "${output}"

#!/usr/bin/env bash
set -euo pipefail

trim() {
  local value="$1"
  value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  printf '%s' "$value"
}

resolve_default_config_path() {
  local cwd
  cwd="$(pwd)"
  local candidates=(
    "$cwd/.db.yaml"
    "$cwd/database.yaml"
    "$HOME/.openclaw/workspace/.db.yaml"
    "$HOME/.openclaw/workspace/database.yaml"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done

  return 1
}

resolve_config_path() {
  local configured_path="${1:-}"
  if [[ -n "$configured_path" ]]; then
    if [[ -f "$configured_path" ]]; then
      printf '%s' "$configured_path"
      return 0
    fi
    echo "Config not found: $configured_path" >&2
    return 1
  fi

  if resolve_default_config_path; then
    return 0
  fi

  echo "Config not found. Looked for .db.yaml/database.yaml in cwd and ~/.openclaw/workspace. Pass --config explicitly." >&2
  return 1
}

strip_quotes() {
  local value="$1"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

# Outputs key=value lines for the mysql block in database.yaml
parse_mysql_config() {
  local file="$1"
  local in_databases=0
  local in_mysql=0
  local db_indent=-1
  local mysql_indent=-1

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    [[ -z "${line//[[:space:]]/}" ]] && continue
    local indent="${line%%[^ ]*}"
    local indent_len=${#indent}
    local trimmed="${line#$indent}"

    if [[ "$trimmed" =~ ^databases:[[:space:]]*$ ]]; then
      in_databases=1
      db_indent=$indent_len
      in_mysql=0
      continue
    fi

    if (( in_databases == 1 )) && (( indent_len <= db_indent )); then
      in_databases=0
      in_mysql=0
    fi

    if (( in_databases == 1 )) && [[ "$trimmed" =~ ^mysql:[[:space:]]*$ ]]; then
      in_mysql=1
      mysql_indent=$indent_len
      continue
    fi

    if (( in_mysql == 1 )) && (( indent_len <= mysql_indent )); then
      in_mysql=0
      continue
    fi

    if (( in_mysql == 1 )) && [[ "$trimmed" =~ ^([a-zA-Z_][a-zA-Z0-9_-]*):[[:space:]]*(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}"
      local value="${BASH_REMATCH[2]}"
      value="$(strip_quotes "$(trim "$value")")"
      printf '%s=%s\n' "$key" "$value"
    fi
  done < "$file"
}

load_mysql_config() {
  local file
  file="$(resolve_config_path "${1:-}")" || exit 1

  MYSQL_HOST=""
  MYSQL_PORT=""
  MYSQL_DATABASE=""
  MYSQL_USERNAME=""
  MYSQL_PASSWORD=""
  MYSQL_CHARSET=""

  while IFS='=' read -r key value; do
    case "$key" in
      host) MYSQL_HOST="$value" ;;
      port) MYSQL_PORT="$value" ;;
      database) MYSQL_DATABASE="$value" ;;
      username) MYSQL_USERNAME="$value" ;;
      password) MYSQL_PASSWORD="$value" ;;
      charset) MYSQL_CHARSET="$value" ;;
    esac
  done < <(parse_mysql_config "$file")

  MYSQL_PORT="${MYSQL_PORT:-3306}"
  MYSQL_CHARSET="${MYSQL_CHARSET:-utf8mb4}"

  if [[ -z "$MYSQL_HOST" || -z "$MYSQL_DATABASE" || -z "$MYSQL_USERNAME" ]]; then
    echo "Missing required MySQL config values in $file" >&2
    exit 1
  fi
}

mysql_cli() {
  local sql="$1"
  mysql --protocol=TCP \
    -h "$MYSQL_HOST" \
    -P "$MYSQL_PORT" \
    -u "$MYSQL_USERNAME" \
    -p"$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    --default-character-set="$MYSQL_CHARSET" \
    --batch \
    --raw \
    --column-names \
    -e "$sql"
}

sql_escape() {
  local value="$1"
  value="${value//"'"/"''"}"
  printf '%s' "$value"
}

ensure_select_only() {
  local sql="$1"
  local lowered
  lowered="$(printf '%s' "$sql" | tr 'A-Z' 'a-z')"
  lowered="${lowered#${lowered%%[![:space:]]*}}"

  if [[ ! "$lowered" =~ ^(select|with)[[:space:]] ]]; then
    echo "Only SELECT/WITH queries are allowed." >&2
    exit 2
  fi

  if printf '%s' "$lowered" | grep -E -q "\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b"; then
    echo "Write or DDL statements are not allowed." >&2
    exit 2
  fi

  if [[ "$lowered" == *";"* ]]; then
    local trimmed="${lowered%%;*}"
    local remainder="${lowered#*$trimmed}"
    if [[ "$remainder" != ";" && "$remainder" != ";"$'\n' ]]; then
      echo "Multiple statements are not allowed." >&2
      exit 2
    fi
  fi
}

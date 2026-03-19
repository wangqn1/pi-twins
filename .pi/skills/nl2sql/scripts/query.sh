#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$base_dir/lib.sh"

usage() {
  cat >&2 <<'USAGE'
Usage:
  query.sh [--config /path/to/.db.yaml] --sql "SELECT ..." [--format markdown|tsv] [--limit N]
  query.sh [--config /path/to/.db.yaml] --file /path/to/query.sql [--format markdown|tsv] [--limit N]

Examples:
  query.sh --config ./.db.yaml --sql "SELECT COUNT(*) AS total FROM users;" --format markdown
  query.sh --sql "SELECT COUNT(*) AS total FROM users;" --format markdown
USAGE
  exit 2
}

config=""
sql=""
sql_file=""
format="markdown"
limit=""
default_limit="200"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      config="${2:-}"
      shift 2
      ;;
    --sql)
      sql="${2:-}"
      shift 2
      ;;
    --file)
      sql_file="${2:-}"
      shift 2
      ;;
    --format)
      format="${2:-}"
      shift 2
      ;;
    --limit)
      limit="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      ;;
  esac
done

if [[ -z "$sql" && -z "$sql_file" ]]; then
  echo "Missing --sql or --file" >&2
  usage
fi

if [[ -n "$sql_file" ]]; then
  if [[ ! -f "$sql_file" ]]; then
    echo "SQL file not found: $sql_file" >&2
    exit 1
  fi
  sql="$(cat "$sql_file")"
fi

ensure_select_only "$sql"
load_mysql_config "$config"

if [[ -z "$limit" ]]; then
  limit="$default_limit"
fi

if ! [[ "$limit" =~ ^[0-9]+$ ]]; then
  echo "--limit must be a non-negative integer." >&2
  exit 2
fi

if [[ "$limit" != "0" ]]; then
  if ! printf '%s' "$sql" | grep -E -i -q "\\blimit\\b"; then
    sql="$(printf '%s' "$sql" | awk -v limit="$limit" '
      BEGIN { IGNORECASE=1 }
      {
        sub(/[;[:space:]]*$/, "")
        print $0 " LIMIT " limit ";"
      }
    ')"
  fi
fi

output="$(mysql_cli "$sql")"

if [[ -z "$output" ]]; then
  echo "No rows returned." >&2
  exit 0
fi

if [[ "$format" == "tsv" ]]; then
  printf '%s\n' "$output"
  exit 0
fi

printf '%s\n' "$output" | awk -F '\t' '
NR==1 {
  printf "|";
  for (i=1; i<=NF; i++) {
    printf " %s |", $i;
  }
  printf "\n|";
  for (i=1; i<=NF; i++) {
    printf " --- |";
  }
  printf "\n";
  next;
}
{
  printf "|";
  for (i=1; i<=NF; i++) {
    printf " %s |", $i;
  }
  printf "\n";
}
'

#!/usr/bin/env bash
set -euo pipefail

base_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$base_dir/lib.sh"

usage() {
  cat >&2 <<'USAGE'
Usage:
  schema.sh [--config /path/to/.db.yaml] [--keywords "foo bar"] [--format markdown|tsv] [--cache-file /path/to/schema.tsv] [--refresh] [--no-cache]

Examples:
  schema.sh --config ./.db.yaml
  schema.sh --keywords "order customer" --format markdown
  schema.sh --refresh
USAGE
  exit 2
}

config=""
keywords=""
format="markdown"
refresh=0
no_cache=0
cache_file="$(pwd)/.nl2sql/schema_cache.tsv"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      config="${2:-}"
      shift 2
      ;;
    --keywords)
      keywords="${2:-}"
      shift 2
      ;;
    --format)
      format="${2:-}"
      shift 2
      ;;
    --cache-file)
      cache_file="${2:-}"
      shift 2
      ;;
    --refresh)
      refresh=1
      shift
      ;;
    --no-cache)
      no_cache=1
      shift
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

if [[ "$format" != "markdown" && "$format" != "tsv" ]]; then
  echo "--format must be one of: markdown, tsv" >&2
  exit 2
fi

if [[ "$no_cache" != "1" && -z "$cache_file" ]]; then
  echo "Missing --cache-file" >&2
  exit 2
fi

build_keyword_regex() {
  local input="$1"
  local regex=""
  local word=""
  while IFS= read -r word || [[ -n "$word" ]]; do
    [[ -z "$word" ]] && continue
    local safe_word
    safe_word="$(printf '%s' "$word" | tr 'A-Z' 'a-z' | sed -e 's/[][(){}.^$*+?|\\]/\\&/g')"
    if [[ -z "$regex" ]]; then
      regex="$safe_word"
    else
      regex="$regex|$safe_word"
    fi
  done < <(printf '%s' "$input" | tr ',|\t' '   ' | tr ' ' '\n')
  printf '%s' "$regex"
}

filter_schema_tsv() {
  local tsv="$1"
  local regex="$2"
  if [[ -z "$regex" ]]; then
    printf '%s\n' "$tsv"
    return 0
  fi

  printf '%s\n' "$tsv" | awk -F '\t' -v regex="$regex" '
NR==1 { print; next }
{
  hay = tolower($1 "\t" $2 "\t" $4);
  if (hay ~ regex) print;
}
'
}

render_tsv() {
  local tsv="$1"
  if [[ "$format" == "tsv" ]]; then
    printf '%s\n' "$tsv"
    return 0
  fi

  printf '%s\n' "$tsv" | awk -F '\t' '
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
}

read_cached_schema() {
  if [[ "$no_cache" == "1" || "$refresh" == "1" ]]; then
    return 1
  fi
  if [[ ! -f "$cache_file" ]]; then
    return 1
  fi
  cat "$cache_file"
}

fetch_schema_from_db() {
  load_mysql_config "$config"
  local schema
  schema="$(sql_escape "$MYSQL_DATABASE")"
  local fetch_schema_sql
  fetch_schema_sql="SELECT table_name, column_name, data_type, column_comment
FROM information_schema.columns
WHERE table_schema = '$schema'
ORDER BY table_name, ordinal_position;"
  mysql_cli "$fetch_schema_sql"
}

schema_tsv="$(read_cached_schema || true)"
if [[ -z "$schema_tsv" ]]; then
  schema_tsv="$(fetch_schema_from_db)"
  if [[ "$no_cache" != "1" ]]; then
    mkdir -p "$(dirname "$cache_file")"
    printf '%s\n' "$schema_tsv" > "$cache_file"
  fi
fi

if [[ -z "$schema_tsv" ]]; then
  echo "No schema rows returned." >&2
  exit 0
fi

keyword_regex="$(build_keyword_regex "$keywords")"
output="$(filter_schema_tsv "$schema_tsv" "$keyword_regex")"

row_count="$(printf '%s\n' "$output" | awk 'END { print NR }')"
if [[ -z "$output" || "$row_count" -le 1 ]]; then
  echo "No schema rows matched." >&2
  exit 0
fi

render_tsv "$output"

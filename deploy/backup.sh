#!/usr/bin/env bash
# Daily Postgres backup. Installed into cron by the deploy job; keeps the last $KEEP_DAYS days.
set -euo pipefail

cd "$(dirname "$0")"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p backups

target="backups/tanomu-$(date +%F).dump"
trap 'rm -f "$target.tmp"' EXIT
docker compose exec -T db pg_dump -U tanomu --format=custom tanomu > "$target.tmp"
if [ ! -s "$target.tmp" ]; then
  echo "backup failed: empty dump" >&2
  exit 1
fi
mv "$target.tmp" "$target"

find backups -name 'tanomu-*.dump' -mtime "+$((KEEP_DAYS - 1))" -delete
echo "backup written: $target"

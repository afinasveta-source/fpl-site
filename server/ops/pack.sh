#!/bin/bash
# Собрать архив канала обновлений сервера: out/fpl-ops.tgz.
# Загружать в хранилище Selectel (бакет facepaintingleague-site) под именем fpl-ops.tgz — сервер применит в течение 5 минут.
set -e
cd "$(dirname "$0")"
cp ../fpl-ingest.py ../fpl-photo-archive.py ../fpl_s3.py .
rm -rf db && mkdir db && cp -r ../db/schema ../db/site_views.sql ../db/fpl-db-setup ../db/fpl-db-export ../db/fpl-db-backup ../db/fpl-db-import ../db/fpl-status db/
mkdir -p ../../out
cp ../kabinet/fpl-kabinet-setup .
rm -rf kabinet-src && mkdir kabinet-src && cp -r ../../kabinet/kabinet ../../kabinet/requirements.txt kabinet-src/
find kabinet-src -name '__pycache__' -prune -exec rm -rf {} +
tar --owner=0 --group=0 -czf ../../out/fpl-ops.tgz apply.sh fpl-sync fpl-ingest.py fpl-photo-archive.py fpl_s3.py db fpl-kabinet-setup kabinet-src
tar -tzvf ../../out/fpl-ops.tgz

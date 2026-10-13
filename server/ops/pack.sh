#!/bin/bash
# Собрать архив канала обновлений сервера: out/fpl-ops.tgz.
# Загружать в хранилище Selectel (бакет facepaintingleague-site) под именем fpl-ops.tgz — сервер применит в течение 5 минут.
set -e
cd "$(dirname "$0")"
cp ../fpl-ingest.py ../fpl-photo-archive.py ../fpl_s3.py .
rm -rf db && mkdir db && cp -r ../db/schema ../db/site_views.sql ../db/fpl-db-setup ../db/fpl-db-export ../db/fpl-db-backup ../db/fpl-db-import ../db/fpl-db-restore ../db/fpl-status db/
mkdir -p ../../out
cp ../kabinet/fpl-kabinet-setup ../kabinet/fpl-media-backup .
rm -rf kabinet-src && mkdir kabinet-src && cp -r ../../kabinet/kabinet ../../kabinet/requirements.txt kabinet-src/
find kabinet-src -name '__pycache__' -prune -exec rm -rf {} +
cp ../kabinet/fpl-kabinet-rehearsal .
# REHEARSAL=on — поднять тестовый кабинет /kabinet-test/, REHEARSAL=off — удалить его; без переменной — не трогать
rm -f rehearsal.on rehearsal.off robot.on; rm -rf robot; EXTRA=""
case "${REHEARSAL:-}" in on|off) touch "rehearsal.$REHEARSAL"; EXTRA="rehearsal.$REHEARSAL" ;; esac
# ROBOT=on — запустить робот-репетицию в тестовом кабинете (нужен поднятый /kabinet-test/)
if [ "${ROBOT:-}" = on ]; then mkdir robot && cp ../../kabinet/sim/robot.py ../../kabinet/sim/oracle.py robot/ && date +%s > robot.on; EXTRA="$EXTRA robot robot.on"; fi
tar --owner=0 --group=0 -czf ../../out/fpl-ops.tgz apply.sh fpl-sync fpl-ingest.py fpl-photo-archive.py fpl_s3.py db fpl-kabinet-setup fpl-media-backup fpl-kabinet-rehearsal kabinet-src $EXTRA
rm -f rehearsal.on rehearsal.off robot.on; rm -rf robot
tar -tzvf ../../out/fpl-ops.tgz

#!/bin/bash
# Собрать архив канала обновлений сервера: out/fpl-ops.tgz (apply.sh + fpl-sync в корне архива).
# Загружать в хранилище Selectel под именем fpl-ops.tgz — сервер применит его в течение 5 минут.
set -e
cd "$(dirname "$0")"
mkdir -p ../../out
tar --owner=0 --group=0 -czf ../../out/fpl-ops.tgz apply.sh fpl-sync
tar -tzvf ../../out/fpl-ops.tgz

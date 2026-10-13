#!/bin/bash
# fpl-ops: настройка сервера сайта FPL. Повторный запуск безопасен (всё идемпотентно).
#  1) сайт берётся из GitHub (afinasveta-source/fpl-site, папка dist/ ветки main);
#  2) приёмник данных из бота понимает закрытые наборы private-… (не публикуются);
#  3) архив фото работ: /var/lib/fpl/archive, cron каждые 10 минут;
#  4) база PostgreSQL сайта (схема 001→008), публичные файлы /data/*.json, ночная копия;
#  5) сводка состояния /data/server-status.json;
#  6) копии базы в закрытый бакет в другом городе (доступ вводится на /admin/backup.html);
#  7) перенос данных из SaleBot в базу (fpl-db-import, каждые 5 минут, если бот прислал новый снимок);
#  9) кабинет на закрытом адресе /kabinet/ (fpl-kabinet-setup), копии фото работ в бакет (fpl-media-backup, каждые 15 минут).
# Если что-то упало — пакет будет применён заново при следующем запуске fpl-ops (через 5 минут).
set -e
cd "$(dirname "$0")"
REPO=afinasveta-source/fpl-site
BRANCH=main
STATUS=/var/lib/fpl/ops-status
fail() { echo "error $(date -u +%Y-%m-%dT%H:%M:%SZ) line $1" > "$STATUS"; rm -f /var/lib/fpl/ops.tgz /var/lib/fpl/ops.etag; /usr/local/bin/fpl-status >/dev/null 2>&1 || true; }
trap 'fail $LINENO' ERR

# 1. Выкладка из GitHub
install -m 0755 fpl-sync /usr/local/bin/fpl-sync
. /etc/fpl.env
if [[ "$ZIP_URL" != *codeload.github.com* ]]; then
  cp /etc/fpl.env "/etc/fpl.env.bak-$(date +%s)"
  grep -q '^ZIP_URL_STORAGE=' /etc/fpl.env || echo "ZIP_URL_STORAGE=$ZIP_URL" >> /etc/fpl.env
  set_kv() { if grep -q "^$1=" /etc/fpl.env; then sed -i "s#^$1=.*#$1=$2#" /etc/fpl.env; else echo "$1=$2" >> /etc/fpl.env; fi; }
  set_kv ZIP_URL "https://codeload.github.com/$REPO/zip/refs/heads/$BRANCH"
  set_kv SHA_URL "https://api.github.com/repos/$REPO/commits/$BRANCH"
  set_kv SITE_DIR "${REPO#*/}-$BRANCH/dist"
  rm -f /var/lib/fpl/etag /var/lib/fpl/sha
fi

# 2. Приёмник: закрытые наборы
mkdir -p /var/lib/fpl/private && chown www-data:www-data /var/lib/fpl/private && chmod 700 /var/lib/fpl/private
if ! cmp -s fpl-ingest.py /opt/fpl/fpl-ingest.py || ! cmp -s fpl_s3.py /opt/fpl/fpl_s3.py; then
  install -m 0755 fpl_s3.py /opt/fpl/fpl_s3.py
  install -m 0755 fpl-ingest.py /opt/fpl/fpl-ingest.py
  grep -q 'FPL_PRIVATE=' /etc/systemd/system/fpl-ingest.service || \
    sed -i 's#^Environment=FPL_DATA=/var/lib/fpl/data#Environment=FPL_PRIVATE=/var/lib/fpl/private FPL_DATA=/var/lib/fpl/data#' /etc/systemd/system/fpl-ingest.service
  systemctl daemon-reload
  systemctl restart fpl-ingest
  echo "fpl-ingest: обновлён и перезапущен"
fi

# 3. Архив фото
mkdir -p /var/lib/fpl/archive/files && chmod 700 /var/lib/fpl/archive /var/lib/fpl/archive/files
install -m 0755 fpl-photo-archive.py /usr/local/bin/fpl-photo-archive
grep -q fpl-photo-archive /etc/cron.d/fpl || \
  printf '7-59/10 * * * * root /usr/local/bin/fpl-photo-archive >> /var/log/fpl-photo-archive.log 2>&1\n' >> /etc/cron.d/fpl

# 4. База
export DEBIAN_FRONTEND=noninteractive
if ! command -v psql >/dev/null || ! ls /usr/lib/postgresql/*/bin/postgres >/dev/null 2>&1; then
  apt-get -o DPkg::Lock::Timeout=600 update -q
  apt-get -o DPkg::Lock::Timeout=600 install -y -q postgresql postgresql-contrib
fi
python3 -c 'import psycopg' 2>/dev/null || python3 -c 'import psycopg2' 2>/dev/null || \
  apt-get -o DPkg::Lock::Timeout=600 install -y -q python3-psycopg || \
  { apt-get -o DPkg::Lock::Timeout=600 update -q && apt-get -o DPkg::Lock::Timeout=600 install -y -q python3-psycopg; } || \
  apt-get -o DPkg::Lock::Timeout=600 install -y -q python3-psycopg2 || \
  echo "fpl-ops: ВНИМАНИЕ: нет драйвера PostgreSQL для Python — перенос из SaleBot не запустится"
mkdir -p /opt/fpl/db && rm -rf /opt/fpl/db/schema && cp -r db/schema db/site_views.sql /opt/fpl/db/
for f in fpl-db-setup fpl-db-export fpl-db-backup fpl-db-import fpl-status; do install -m 0755 "db/$f" "/usr/local/bin/$f"; done
/usr/local/bin/fpl-db-setup /opt/fpl/db
grep -q fpl-db-export /etc/cron.d/fpl || \
  printf '*/10 * * * * root /usr/local/bin/fpl-db-export >> /var/log/fpl-db.log 2>&1\n17 3 * * * root /usr/local/bin/fpl-db-backup >> /var/log/fpl-db.log 2>&1\n' >> /etc/cron.d/fpl
# копия базы — каждый час (было раз в сутки: во время Игры потеря до суток работ и голосов; учения 13.10)
sed -i 's#^17 3 \* \* \* root /usr/local/bin/fpl-db-backup#17 * * * * root /usr/local/bin/fpl-db-backup#' /etc/cron.d/fpl
for f in fpl-db-restore; do [ -f "db/$f" ] && install -m 0755 "db/$f" "/usr/local/bin/$f"; done
grep -q offsite-if-missing /etc/cron.d/fpl || \
  printf '47 * * * * root /usr/local/bin/fpl-db-backup --offsite-if-missing >> /var/log/fpl-db.log 2>&1\n' >> /etc/cron.d/fpl
grep -q fpl-status /etc/cron.d/fpl || \
  printf '*/10 * * * * root /usr/local/bin/fpl-status >/dev/null 2>&1\n' >> /etc/cron.d/fpl
grep -q fpl-db-import /etc/cron.d/fpl || \
  printf '3-59/5 * * * * root /usr/local/bin/fpl-db-import >> /var/log/fpl-db.log 2>&1\n' >> /etc/cron.d/fpl
/usr/local/bin/fpl-db-export
[ -f /var/backups/fpl/last-ok ] || /usr/local/bin/fpl-db-backup

# 8. nginx: своя страница 404 вместо главной (с проверкой конфигурации и откатом)
NG=/etc/nginx/sites-available/fpl
if [ -f "$NG" ] && grep -q 'error_page 404 /index.html;' "$NG"; then
  cp "$NG" "$NG.bak-404"
  sed -i 's#error_page 404 /index.html;#error_page 404 /404.html;#g' "$NG"
  if nginx -t >/dev/null 2>&1; then systemctl reload nginx; echo "nginx: страница 404"; else cp "$NG.bak-404" "$NG"; echo "nginx: правка 404 откатана"; fi
fi

# 9. Кабинет (закрытый адрес /kabinet/). Сбой кабинета не мешает сайту и базе: итог — в /var/lib/fpl/kabinet-status.
if [ -d kabinet-src ]; then
  install -m 0755 fpl-kabinet-setup /usr/local/bin/fpl-kabinet-setup
  rm -rf /opt/fpl/kabinet-src && mkdir -p /opt/fpl && cp -r kabinet-src /opt/fpl/kabinet-src
  /usr/local/bin/fpl-kabinet-setup /opt/fpl/kabinet-src || echo "кабинет: ошибка установки (см. /var/lib/fpl/kabinet-status)"
  if [ -f fpl-media-backup ]; then
    install -m 0755 fpl-media-backup /usr/local/bin/fpl-media-backup
    grep -q fpl-media-backup /etc/cron.d/fpl || \
      printf '11-59/15 * * * * root flock -n /run/lock/fpl-media-backup.lock /usr/local/bin/fpl-media-backup >> /var/log/fpl-media-backup.log 2>&1\n' >> /etc/cron.d/fpl
  fi
fi

# 10. Тестовый кабинет для генеральной репетиции (/kabinet-test/): пакет с rehearsal.on — поднять, с rehearsal.off — удалить.
#     Обычный пакет его не трогает, только перезапускает на новом коде.
if [ -f fpl-kabinet-rehearsal ]; then install -m 0755 fpl-kabinet-rehearsal /usr/local/bin/fpl-kabinet-rehearsal; fi
if [ -f rehearsal.off ]; then
  /usr/local/bin/fpl-kabinet-rehearsal off || echo "репетиция: ошибка удаления"
elif [ -f rehearsal.on ]; then
  /usr/local/bin/fpl-kabinet-rehearsal on || echo "репетиция: ошибка (см. /var/lib/fpl/kabinet-test-status)"
elif systemctl is-enabled --quiet fpl-kabinet-test 2>/dev/null; then
  # схема тестовой базы — та же версия, что у кода (иначе тестовый кабинет не стартует после новой миграции)
  FPL_DB_NAME_OVERRIDE=fpl_rehearsal_test /usr/local/bin/fpl-db-setup /opt/fpl/db >/dev/null || echo "репетиция: схема тестовой базы не обновилась"
  systemctl restart fpl-kabinet-test || true
fi

# 11. Робот-репетиция (пакет с robot.on): Игра роботов в ТЕСТОВОМ кабинете, в фоне ~1 час; итог — /data/robot-report.json
# Один запуск на пакет: метка прогона — содержимое robot.on (пакет пишет туда время сборки).
RUN_ID=$( [ -f robot.on ] && tr -dc '0-9' < robot.on | head -c 20 || true)
if [ -f robot.on ] && [ -d robot ] && [ -n "$RUN_ID" ] && [ ! -f "/var/lib/fpl/robot-run-$RUN_ID" ] \
   && systemctl is-active --quiet fpl-kabinet-test; then
  FREE_MB=$(df -Pm /var/lib/fpl | awk 'NR==2{print $4}')
  if [ "${FREE_MB:-0}" -lt 3000 ]; then
    echo "робот-репетиция: не запущен — на диске меньше 3 ГБ (${FREE_MB} МБ)"
  elif ! systemctl list-units --type=service --state=running | grep -q 'fpl-robot'; then
    rm -rf /opt/fpl/robot && cp -r robot /opt/fpl/robot
    touch "/var/lib/fpl/robot-run-$RUN_ID"
    BASE="https://${DOMAIN:-facepaintingleague.com}/kabinet-test"
    curl -sf --max-time 10 "$BASE/health" >/dev/null || BASE="http://127.0.0.1:8101"
    systemd-run --unit="fpl-robot-$(date +%s)" --collect -p MemoryMax=250M -p OOMScoreAdjust=900 -p CPUWeight=20 -p Nice=10 \
      -p EnvironmentFile=/etc/fpl-kabinet-test.env -p Environment=PYTHONPATH=/opt/fpl/kabinet/code \
      -p WorkingDirectory=/opt/fpl/robot /opt/fpl/kabinet/venv/bin/python /opt/fpl/robot/robot.py --base "$BASE" --n 200 --minutes 12 \
      && echo "робот-репетиция: запущен ($BASE)" || echo "робот-репетиция: не запустился"
  fi
fi

/usr/local/bin/fpl-sync || true
/usr/local/bin/fpl-photo-archive || true
echo "ok $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS"
/usr/local/bin/fpl-status || true
echo "fpl-ops: готово, сайт $(cat /var/www/fpl/current/version.txt 2>/dev/null || echo '?')"

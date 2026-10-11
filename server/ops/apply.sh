#!/bin/bash
# fpl-ops: настройка сервера сайта FPL. Повторный запуск безопасен (всё идемпотентно).
#  1) сайт берётся из GitHub (afinasveta-source/fpl-site, папка dist/ ветки main);
#  2) приёмник данных из бота понимает закрытые наборы private-… (не публикуются);
#  3) архив фото работ: /var/lib/fpl/archive, cron каждые 10 минут.
set -e
cd "$(dirname "$0")"
REPO=afinasveta-source/fpl-site
BRANCH=main

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
if ! cmp -s fpl-ingest.py /opt/fpl/fpl-ingest.py; then
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

/usr/local/bin/fpl-sync || true
/usr/local/bin/fpl-photo-archive || true
echo "fpl-ops: готово, сайт $(cat /var/www/fpl/current/version.txt 2>/dev/null || echo '?')"

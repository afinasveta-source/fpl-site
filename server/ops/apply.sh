#!/bin/bash
# fpl-ops: перевести выкладку сайта на GitHub — репозиторий afinasveta-source/fpl-site, папка dist/ ветки main.
# Повторный запуск безопасен. Откат: ZIP_URL=$ZIP_URL_STORAGE и удалить SHA_URL, SITE_DIR в /etc/fpl.env.
set -e
cd "$(dirname "$0")"
REPO=afinasveta-source/fpl-site
BRANCH=main
install -m 0755 fpl-sync /usr/local/bin/fpl-sync
cp /etc/fpl.env "/etc/fpl.env.bak-$(date +%s)"
. /etc/fpl.env
case "$ZIP_URL" in *codeload.github.com*) ;; *) grep -q '^ZIP_URL_STORAGE=' /etc/fpl.env || echo "ZIP_URL_STORAGE=$ZIP_URL" >> /etc/fpl.env ;; esac
set_kv() { if grep -q "^$1=" /etc/fpl.env; then sed -i "s#^$1=.*#$1=$2#" /etc/fpl.env; else echo "$1=$2" >> /etc/fpl.env; fi; }
set_kv ZIP_URL "https://codeload.github.com/$REPO/zip/refs/heads/$BRANCH"
set_kv SHA_URL "https://api.github.com/repos/$REPO/commits/$BRANCH"
set_kv SITE_DIR "${REPO#*/}-$BRANCH/dist"
rm -f /var/lib/fpl/etag /var/lib/fpl/sha
echo "fpl.env:"; grep -v KEY /etc/fpl.env
/usr/local/bin/fpl-sync && echo "fpl-sync: ok, $(cat /var/www/fpl/current/version.txt 2>/dev/null || echo 'GitHub пока не ответил — повторит cron')"

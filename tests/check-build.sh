#!/bin/bash
# Проверка собранного dist/ перед push: поднимает локальный сервер и гоняет site-check.js в локальном режиме.
# Выход 0 — поломок нет (заглушки контента выводятся отдельно и выкладку не блокируют).
set -e
cd "$(dirname "$0")/.."
PORT=${PORT:-8099}
python3 -m http.server "$PORT" -d dist >/dev/null 2>&1 & SRV=$!
trap 'kill $SRV' EXIT
sleep 1
export NODE_PATH=${NODE_PATH:-$(npm root -g)}
set +e
FPL_LOCAL=1 node tests/site-check.js "http://127.0.0.1:$PORT" > tests/last-report.json
code=$?
python3 -c "
import json; r=json.load(open('tests/last-report.json'))
print('Поломки:', len(r['problems'])); [print('  -', p) for p in r['problems']]
print('Заглушки/пример-данные (не блокируют):', len(r['content']))
print('Диплом-образец:', r.get('diploma_sample'))"
exit $code

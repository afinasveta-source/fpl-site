#!/bin/bash
# Полная сборка сайта FPL: src/ → dist/
# Порядок: страницы → английская версия → SEO-раскладка (EN в корне, RU в /ru/) → настоящие ссылки.
# Нужно: python3 + beautifulsoup4 (pip install beautifulsoup4).
set -e
cd "$(dirname "$0")"
python3 build_site.py
python3 i18n/build_en.py
python3 seo.py
python3 links.py
echo "Готово: ${FPL_DIST:-$(cd .. && pwd)/dist}"

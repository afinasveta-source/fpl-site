# Пути сборки сайта FPL — относительно репозитория.
# FPL_DIST можно переопределить (например, собрать во временную папку для сравнения).
import os
BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
SRC = os.path.join(ROOT, 'src')                  # исходные страницы (RU) и assets/
DIST = os.environ.get('FPL_DIST') or os.path.join(ROOT, 'dist')   # готовый сайт
I18N = os.path.join(BUILD, 'i18n')
PRIVACY = os.path.join(BUILD, 'privacy')
OG = os.path.join(BUILD, 'og')

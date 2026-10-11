# FPL: настоящие ссылки в собранном сайте. Запускать после seo.py.
# Адреса — здесь, в одном месте. Когда появится регистрация на сайте, меняется только JOIN.
import os, re, glob
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # build/
from paths import SRC, DIST, I18N, PRIVACY, OG
D = DIST
JOIN = 'https://t.me/facepaintingleaguebot'      # «Участвовать» — пока бот
IG   = 'https://www.instagram.com/facepaintingleague/'  # «Следить»
TG   = 'https://t.me/maskarad_grim'
VK   = 'https://vk.ru/publicmaskarad'
MAIL = 'mailto:info@maskarad-grim.ru'
EXT = ' target="_blank" rel="noopener"'

def fix(s, en):
    n0 = s
    # кнопки-«пустышки» → ссылки
    def btn(m):
        attrs, text = m.group(1), m.group(2).strip()
        attrs = re.sub(r'\s*type="button"', '', attrs)
        if re.match(r'(Участвовать|Join)$', text):
            return f'<a{attrs} href="{JOIN}"{EXT}>{text}</a>'
        if re.match(r'(Следить за лигой|Следить|Follow the league|Follow)$', text):
            label = ('Follow on Instagram*' if 'league' in text or 'wide' in attrs and 'mm-' in attrs else 'Instagram*') if en else ('Следить в Instagram*' if 'лигой' in text else 'Instagram*')
            return f'<a{attrs} href="{IG}"{EXT}>{label}</a>'
        return m.group(0)
    s = re.sub(r'<button((?:\s+(?:class|style|type)="[^"]*")*)>\s*([^<]*?)\s*</button>', btn, s)
    # соцсети
    s = s.replace('<a href="#">Telegram</a>', f'<a href="{TG}"{EXT}>Telegram</a>')
    s = s.replace('<a href="#">ВКонтакте</a>', f'<a href="{VK}"{EXT}>ВКонтакте</a>').replace('<a href="#">VK</a>', f'<a href="{VK}"{EXT}>VK</a>')
    s = s.replace('<a href="#">Instagram*</a>', f'<a href="{IG}"{EXT}>Instagram*</a>')
    s = s.replace('<a href="#">Telegram<i>→</i></a>', f'<a href="{TG}"{EXT}>Telegram<i>→</i></a>')
    s = s.replace('<a href="#">ВКонтакте<i>→</i></a>', f'<a href="{VK}"{EXT}>ВКонтакте<i>→</i></a>').replace('<a href="#">VK<i>→</i></a>', f'<a href="{VK}"{EXT}>VK<i>→</i></a>')
    s = re.sub(r'<a href="#">(<span>)?Instagram\* <small>@(?:\[(?:ник|handle)\]|facepaintingleague)</small>', lambda m: f'<a href="{IG}"{EXT}>{m.group(1) or ""}Instagram* <small>@facepaintingleague</small>', s)
    # «Участвовать →» и документы/вопросы в боте
    for t in ['Участвовать →', 'Join →', 'Задать вопрос в боте', 'Ask in the bot', 'Читать в боте', 'Read in the bot']:
        s = re.sub(r'<a class="(btnC|ghostC)" href="#">' + re.escape(t) + '</a>', lambda m: f'<a class="{m.group(1)}" href="{JOIN}"{EXT}>{t}</a>', s)
    s = s.replace('<a class="btnC" href="#">Скачать PDF</a>', f'<a class="btnC" href="{JOIN}"{EXT}>Открыть в боте</a>')
    s = s.replace('<a class="btnC" href="#">Download PDF</a>', f'<a class="btnC" href="{JOIN}"{EXT}>Open in the bot</a>')
    s = s.replace('<a class="rldoc" href="#">', f'<a class="rldoc" href="{JOIN}"{EXT}>')
    # партнёрство и пресс-кит — на почту
    s = s.replace('<a class="btn-outline" href="#">Стать партнёром</a>', f'<a class="btn-outline" href="{MAIL}?subject=Партнёрство">Стать партнёром</a>')
    s = s.replace('<a class="btn-outline" href="#">Become a partner</a>', f'<a class="btn-outline" href="{MAIL}?subject=Partnership">Become a partner</a>')
    s = s.replace('<a class="text-link" href="#">Скачать пресс-кит</a><span>[почта для связи]</span>', f'<a class="text-link" href="{MAIL}?subject=Пресс-кит">Запросить пресс-кит</a><span>info@maskarad-grim.ru</span>')
    s = s.replace('<a class="text-link" href="#">Download press kit</a><span>[contact email]</span>', f'<a class="text-link" href="{MAIL}?subject=Press%20kit">Request the press kit</a><span>info@maskarad-grim.ru</span>')
    # главная: большая кнопка в герое — сразу в бот
    s = re.sub(r'<a class="btnC" href="#how"', f'<a class="btnC" href="{JOIN}"{EXT}', s)
    s = re.sub(r'<a class="btnC" (data-en="[^"]*") href="#how"', lambda m: f'<a class="btnC" {m.group(1)} href="{JOIN}"{EXT}', s)
    # подпись под главной кнопкой
    return s

cnt = 0
for f in glob.glob(D + '/*.html') + glob.glob(D + '/ru/*.html'):
    if os.path.basename(f).startswith(('google', 'yandex')): continue
    s = open(f, encoding='utf-8').read(); en = '/ru/' not in f
    t = fix(s, en)
    if t != s: cnt += 1; open(f, 'w', encoding='utf-8').write(t)
# стили: ссылки выглядят как кнопки
css = D + '/assets/site.css'
c = open(css, encoding='utf-8').read()
if 'a.btn-wide' not in c:
    c += '\n/* кнопки-ссылки */\na.btn-wide,a.btn-outline{text-decoration:none; display:inline-flex; align-items:center; justify-content:center; text-align:center}\n.mbar a.btn-wide{display:flex}\n.mmenu-foot a.btn-wide{display:flex}\n'
    open(css, 'w', encoding='utf-8').write(c)
print('изменено файлов:', cnt)


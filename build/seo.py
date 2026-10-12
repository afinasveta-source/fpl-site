# SEO-слой сайта FPL: английский — основная версия в корне, русский — в /ru/.
# Запускать после build_site.py и i18n/build_en.py.
import os, re, json, shutil, html
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # build/
from paths import SRC, DIST, I18N, PRIVACY, OG

O = SRC
D = DIST
import hashlib, datetime
VER = {f: hashlib.sha256(open(os.path.join(SRC, 'assets', f), 'rb').read()).hexdigest()[:10] for f in ('site.css', 'consent.js', 'fpl-data.js', 'a11y.js')}
# шрифты первого экрана: грузятся сразу, чтобы текст не «прыгал» при подмене шрифта
FONTS = {'ru': ['manrope-cyrillic-500', 'manrope-cyrillic-400', 'unbounded-cyrillic-400', 'unbounded-cyrillic-700'],
         'en': ['manrope-latin-500', 'manrope-latin-400', 'unbounded-latin-400', 'unbounded-latin-700']}
SKIP = {'ru': 'Перейти к содержанию', 'en': 'Skip to content'}
TODAY = datetime.date.today().isoformat()
DOMAIN = 'https://facepaintingleague.com'
PAGES = ['index', 'games', 'rating', 'master', 'gallery', 'find', 'diploma', 'rules', 'about', 'privacy', 'feedback']

def url(lang, p):
    base = DOMAIN + ('/ru/' if lang == 'ru' else '/')
    return base if p == 'index' else base + p + '.html'

META = {
 'en': {
  'index':  ('Face Painting League — online face painting competition', 'An online league for face painters from any country: a new brief every round, professional judges, leagues, a public rating and verifiable certificates.'),
  'games':  ('Games & calendar — Face Painting League', 'Season 1 of Face Painting League: three Games and a Super Final, with short challenges in between. See what is inside the next Game and how to join.'),
  'rating': ('Face painter rankings — FPL Rating', 'The FPL Rating of face painters. It changes after every round and weighs opponent strength; it stays provisional during calibration.'),
  'master': ('Artist pages — coming soon | Face Painting League', 'Face Painting League artist pages open after the Game 01 final: FPL Rating, league, awards and judged works — for artists who allow a public page.'),
  'gallery':('Face painting gallery — works from FPL Games', 'Gallery of face painting works by Face Painting League artists. Opens after the Game 01 final; works are published only with the artists’ consent.'),
  'find':   ('Find a face painter — FPL artists taking bookings', 'Directory of Face Painting League face painters taking bookings. Opens after the Game 01 final: artists judged by professionals, with rating and awards.'),
  'diploma':('Certificate check — Face Painting League', 'Verify a Face Painting League certificate by its number (FPL-S1-01-G-0247) or QR code: who it was issued to, for which Game and with what result.'),
  'rules':  ('Rules & FAQ — Face Painting League', 'The Face Painting League rules in plain words: how to join, submit a work, how judging, rating and leagues work, certificates and the Super Final.'),
  'privacy':('Privacy policy — Face Painting League', 'How Face Painting League processes the personal data of participants and website visitors: what we collect, why, where it is stored and how to exercise your rights.'),
  'feedback':('Ideas for the league — Face Painting League', 'Send the Face Painting League organizers an anonymous suggestion about the Games, briefs, judging or the website. No sign-in needed.'),
  'about':  ('About Face Painting League by MAGFACE', 'Face Painting League is an online league for face painters by MAGFACE, grown out of seven years of face painting marathons with 1,400+ artists.'),
 },
 'ru': {
  'index':  ('Face Painting League — онлайн-лига аквагримёров', 'Онлайн-лига для мастеров аквагрима из любой страны: новое задание каждый тур, профессиональное жюри, лиги, публичный рейтинг и проверяемые дипломы.'),
  'games':  ('Игры и календарь — Face Painting League', 'Сезон 1 Face Painting League: три Игры и Суперфинал, между Играми — короткие челленджи. Что внутри следующей Игры и как в неё попасть.'),
  'rating': ('Рейтинг мастеров аквагрима — FPL Rating', 'Рейтинг FPL мастеров аквагрима. Меняется после каждого тура с учётом силы соперников; пока идёт калибровка, он предварительный.'),
  'master': ('Страницы мастеров — скоро | Face Painting League', 'Страницы мастеров Face Painting League откроются после финала Игры 01: рейтинг FPL, лига, награды и работы, оценённые жюри, — у тех, кто разрешит публичную страницу.'),
  'gallery':('Галерея аквагрима — работы участников FPL', 'Галерея работ мастеров Face Painting League. Откроется после финала Игры 01; работы публикуются только с согласия авторов.'),
  'find':   ('Найти мастера аквагрима — мастера FPL', 'Каталог мастеров аквагрима Face Painting League, которые принимают заказы. Откроется после финала Игры 01: работы оценены жюри, есть рейтинг и награды.'),
  'diploma':('Проверка диплома — Face Painting League', 'Проверьте диплом Face Painting League по номеру (FPL-S1-01-G-0247) или QR-коду: кому, за какую Игру и с каким результатом он выдан.'),
  'rules':  ('Правила и вопросы — Face Painting League', 'Правила лиги простыми словами: как участвовать и сдать работу, как устроены оценка, рейтинг и лиги, диплом и Суперфинал.'),
  'privacy':('Политика конфиденциальности — Face Painting League', 'Как Face Painting League обрабатывает персональные данные участников и посетителей сайта: что собираем, зачем, где храним и как реализовать свои права.'),
  'feedback':('Пожелания лиге — Face Painting League', 'Анонимно напишите организаторам Face Painting League, что улучшить в Играх, заданиях, судействе или на сайте. Без входа в кабинет.'),
  'about':  ('О лиге — Face Painting League by MAGFACE', 'Face Painting League — онлайн-лига аквагримёров от MAGFACE. Выросла из семи лет марафонов по аквагриму, в которых участвовали 1400+ мастеров.'),
 }
}
CRUMB = {'en': {'index':'Home','games':'Games','rating':'Rating','master':'Artist','gallery':'Gallery','find':'Find an artist','diploma':'Certificate check','rules':'Rules','about':'About','privacy':'Privacy policy','feedback':'Ideas for the league'},
         'ru': {'index':'Главная','games':'Игры','rating':'Рейтинг','master':'Мастер','gallery':'Галерея','find':'Найти мастера','diploma':'Проверка диплома','rules':'Правила','about':'О лиге','privacy':'Политика конфиденциальности','feedback':'Пожелания лиге'}}
PAGETYPE = {'index':'WebPage','games':'CollectionPage','rating':'CollectionPage','master':'WebPage','gallery':'CollectionPage',
            'find':'CollectionPage','diploma':'WebPage','rules':'FAQPage','about':'AboutPage','privacy':'WebPage','feedback':'ContactPage'}
ORG_DESC = {'en':'Online league for face painters by MAGFACE: Games with judged rounds, leagues, an FPL Rating and verifiable certificates.',
            'ru':'Онлайн-лига аквагримёров от MAGFACE: Игры с оценкой жюри, лиги, рейтинг FPL и проверяемые дипломы.'}

def org(lang='en'):
    return {"@type":"Organization","@id":DOMAIN+"/#org","name":"Face Painting League","alternateName":"FPL",
            "url":DOMAIN+"/","logo":DOMAIN+"/assets/favicon.svg",
            "brand":{"@type":"Brand","name":"MAGFACE"},
            "description":ORG_DESC[lang]}

def strip(s): return html.unescape(re.sub(r'<[^>]+>','',s)).strip()

def jsonld(lang, p, s):
    title, desc = META[lang][p]
    g = [org(lang)]
    if p == 'index':
        g.append({"@type":"WebSite","@id":DOMAIN+"/#site","url":DOMAIN+"/","name":"Face Painting League",
                  "inLanguage":["en","ru"],"publisher":{"@id":DOMAIN+"/#org"}})
    page = {"@type":PAGETYPE[p],"@id":url(lang,p)+"#page","url":url(lang,p),"name":title,"description":desc,
            "inLanguage":lang,"isPartOf":{"@id":DOMAIN+"/#site"},"publisher":{"@id":DOMAIN+"/#org"}}
    if p != 'index':
        page["breadcrumb"] = {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":CRUMB[lang]['index'],"item":url(lang,'index')},
            {"@type":"ListItem","position":2,"name":CRUMB[lang][p],"item":url(lang,p)}]}
    if p == 'rules':
        qa = re.findall(r'<details[^>]*>\s*<summary>(.*?)</summary>\s*<p>(.*?)</p>\s*</details>', s, re.S)
        page["mainEntity"] = [{"@type":"Question","name":strip(q),"acceptedAnswer":{"@type":"Answer","text":strip(a)}} for q,a in qa]
    if p == 'about':
        page["about"] = {"@id":DOMAIN+"/#org"}
    g.append(page)
    return json.dumps({"@context":"https://schema.org","@graph":g}, ensure_ascii=False, indent=1)

NOINDEX = {'master'}   # страницы мастеров — после финала Игры 01; вернуть в индекс, когда появятся профили

def head_block(lang, p, s):
    title, desc = META[lang][p]
    og_img = DOMAIN + f'/assets/og-{lang}.png'
    alt = [f'<link rel="alternate" hreflang="en" href="{url("en",p)}">',
           f'<link rel="alternate" hreflang="ru" href="{url("ru",p)}">',
           f'<link rel="alternate" hreflang="x-default" href="{url("en",p)}">']
    tags = [
     '<meta charset="utf-8">',
     f'<title>{html.escape(title)}</title>',
     f'<meta name="description" content="{html.escape(desc)}">',
     f'<link rel="canonical" href="{url(lang,p)}">', *alt,
     '<meta name="robots" content="%s">' % ('noindex,follow' if p in NOINDEX else 'index,follow,max-image-preview:large'),
     '<meta name="theme-color" content="#1E1B18">',
     *[f'<link rel="preload" href="/assets/fonts/{f}-normal.woff2" as="font" type="font/woff2" crossorigin>' for f in FONTS[lang]],
     f'<link rel="icon" href="{"../" if lang=="ru" else ""}assets/favicon.svg" type="image/svg+xml">',
     '<meta property="og:type" content="website">',
     '<meta property="og:site_name" content="Face Painting League">',
     f'<meta property="og:title" content="{html.escape(title)}">',
     f'<meta property="og:description" content="{html.escape(desc)}">',
     f'<meta property="og:url" content="{url(lang,p)}">',
     f'<meta property="og:image" content="{og_img}">',
     '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
     f'<meta property="og:locale" content="{"en_US" if lang=="en" else "ru_RU"}">',
     f'<meta property="og:locale:alternate" content="{"ru_RU" if lang=="en" else "en_US"}">',
     '<meta name="twitter:card" content="summary_large_image">',
     f'<meta name="twitter:title" content="{html.escape(title)}">',
     f'<meta name="twitter:description" content="{html.escape(desc)}">',
     f'<meta name="twitter:image" content="{og_img}">',
     f'<script type="application/ld+json">\n{jsonld(lang,p,s)}\n</script>']
    return '<!-- SEO -->\n' + '\n'.join(tags) + '\n<!-- /SEO -->\n'

def process(path, lang, p):
    s = open(path, encoding='utf-8').read()
    s = re.sub(r'<!-- SEO -->.*?<!-- /SEO -->\n', '', s, flags=re.S)
    s = re.sub(r'<title>.*?</title>\s*', '', s, count=1, flags=re.S)
    s = re.sub(r'<meta charset="[^"]*">\s*', '', s, flags=re.I)
    s = s.replace('<head>', '<head>\n' + head_block(lang, p, s), 1)
    s = re.sub(r'<html[^>]*>', f'<html lang="{lang}">', s, count=1)
    # переключатель языка под новую раскладку: EN в корне, RU в /ru/
    if lang == 'en':
        s = s.replace(f'data-href="../{p}.html"', f'data-href="ru/{p}.html"')
    else:
        s = s.replace(f'data-href="en/{p}.html"', f'data-href="../{p}.html"')
        s = s.replace('href="assets/', 'href="../assets/')
        s = s.replace('src="assets/', 'src="../assets/')
    # плашка cookie + Яндекс Метрика (после согласия)
    if 'consent.js' not in s:
        s = s.replace('</body>', f'<script src="{"../" if lang=="ru" else ""}assets/consent.js?v=1" defer></script>\n</body>', 1)
    # клавиатура: меню не теряет фокус; ссылка «Перейти к содержанию» первой в странице
    if 'a11y.js' not in s:
        s = s.replace('</body>', f'<script src="{"../" if lang=="ru" else ""}assets/a11y.js?v=1" defer></script>\n</body>', 1)
    if 'class="skip-link"' not in s:
        nav_end = s.find('</nav>')
        m = re.compile(r'<section(?P<a>[^>]*)>').search(s, nav_end if nav_end > 0 else 0)
        if m:
            idm = re.search(r'\bid="([^"]+)"', m.group('a'))
            target = idm.group(1) if idm else 'content'
            if not idm:
                s = s[:m.start()] + '<section id="content"' + m.group('a') + '>' + s[m.end():]
            s = re.sub(r'(<body[^>]*>)', lambda b: b.group(1) + f'\n<a class="skip-link" href="#{target}">{SKIP[lang]}</a>', s, count=1)
    for f in ('site.css', 'consent.js', 'fpl-data.js', 'a11y.js'):
        s = re.sub(r'(assets/' + re.escape(f) + r')(\?v=[0-9a-z]+)?"', lambda m: m.group(1) + '?v=' + VER[f] + '"', s)
    open(path, 'w', encoding='utf-8').write(s)

def relayout():
    # RU из корня → /ru/, EN из /en/ → корень
    tmp = D + '_tmp'
    if os.path.isdir(tmp): shutil.rmtree(tmp)
    os.makedirs(tmp + '/ru')
    for p in PAGES:
        shutil.copy(f'{D}/{p}.html', f'{tmp}/ru/{p}.html')
        shutil.copy(f'{D}/en/{p}.html', f'{tmp}/{p}.html')
    shutil.rmtree(D); shutil.move(tmp, D)

def assets():
    os.makedirs(D + '/assets', exist_ok=True)
    shutil.copy(O + '/assets/site.css', D + '/assets/site.css')
    shutil.copy(O + '/assets/consent.js', D + '/assets/consent.js')
    shutil.copy(O + '/assets/fpl-data.js', D + '/assets/fpl-data.js')
    shutil.copy(O + '/assets/a11y.js', D + '/assets/a11y.js')
    shutil.copytree(O + '/assets/fonts', D + '/assets/fonts', dirs_exist_ok=True)
    if os.path.isdir(O + '/assets/img'): shutil.copytree(O + '/assets/img', D + '/assets/img', dirs_exist_ok=True)
    # служебные страницы (не индексируются): /admin/
    if os.path.isdir(O + '/admin'): shutil.copytree(O + '/admin', D + '/admin', dirs_exist_ok=True)
    # файлы подтверждения для Google Search Console / Яндекс Вебмастера — в корень сайта
    for f in os.listdir(O + '/assets/verify'): shutil.copy(O + '/assets/verify/' + f, D + '/' + f)
    open(D + '/assets/favicon.svg', 'w').write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1E1B18"/>'
        '<text x="32" y="41" text-anchor="middle" font-family="Arial Black,Arial,sans-serif" font-weight="900" font-size="22" fill="#F2601F">FPL</text></svg>')
    # страница 404 (RU + EN), пути абсолютные — открывается по любому несуществующему адресу
    open(D + '/404.html', 'w', encoding='utf-8').write(f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Страница не найдена · Page not found — Face Painting League</title>
<meta name="robots" content="noindex"><link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/site.css?v={VER['site.css']}">
<style>.nf{{max-width:720px; margin:0 auto; padding:72px 16px 80px}} .nf-logo{{font:800 30px/1 var(--f-display); color:#F2601F; text-decoration:none}}
.nf h1{{margin:40px 0 12px}} .nf p{{font-size:17px; line-height:1.55; color:#4A423B; margin:0 0 22px}} .nf hr{{border:0; border-top:1px solid #E2DBD2; margin:40px 0}}
.nf a.btn-wide{{display:inline-block; text-decoration:none; text-align:center; min-width:220px}}</style></head>
<body><main class="nf">
<a class="nf-logo" href="/ru/">FPL</a>
<h1 class="h2">Страница не найдена</h1>
<p>Возможно, адрес изменился или в нём опечатка.</p>
<a class="btn-wide" href="/ru/">На главную</a>
<hr lang="en">
<h2 class="h2" lang="en">Page not found</h2>
<p lang="en">The address may have changed or contain a typo.</p>
<a class="btn-wide" href="/" lang="en">Go to the home page</a>
</main></body></html>
''')
    for f in ('og-en.png', 'og-ru.png'):
        src = os.path.join(OG, f)
        if os.path.exists(src): shutil.copy(src, D + '/assets/' + f)

def crawler_files():
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for p in PAGES:
        if p in NOINDEX: continue
        for lang in ('en', 'ru'):
            sm.append(f'  <url><loc>{url(lang,p)}</loc><lastmod>{TODAY}</lastmod>'
                      f'<xhtml:link rel="alternate" hreflang="en" href="{url("en",p)}"/>'
                      f'<xhtml:link rel="alternate" hreflang="ru" href="{url("ru",p)}"/>'
                      f'<xhtml:link rel="alternate" hreflang="x-default" href="{url("en",p)}"/></url>')
    sm.append('</urlset>')
    open(D + '/sitemap.xml', 'w').write('\n'.join(sm) + '\n')
    open(D + '/robots.txt', 'w').write(f'''# Face Painting League
# Одна группа на всех: поисковые и ИИ-роботы приглашены, служебные адреса закрыты.
User-agent: *
User-agent: Googlebot
User-agent: Bingbot
User-agent: YandexBot
User-agent: GPTBot
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: ClaudeBot
User-agent: Claude-SearchBot
User-agent: PerplexityBot
User-agent: Google-Extended
User-agent: Applebot-Extended
Allow: /
Disallow: /api/
Disallow: /account/
Disallow: /admin/

Sitemap: {DOMAIN}/sitemap.xml
''')
    open(D + '/llms.txt', 'w').write(f'''# Face Painting League (FPL)

> Face Painting League (FPL) is an online league for face painters, run by MAGFACE. Artists from any country take part in online Games made of judged rounds: each round has a new brief, works are scored anonymously by professional judges, and every artist gets an FPL Rating. In Game 01 the leagues are League A and League B (set by round 1); from Game 02 the rating places artists into the Bronze, Silver or Gold league. A season has three Games and a Super Final, with short open challenges in between. Artists who submit all works by the end of a Game receive a numbered, verifiable certificate.

Key facts:
- Organizer: MAGFACE, after seven years of face painting marathons (1,400+ artists, 30,000+ works).
- Season 1: three Games and a Super Final. The first Game is free for new participants.
- Judging: anonymous; head-to-head or by criteria depending on the round. TOP WORK marks the best works of each round.
- Certificates: numbered FPL-S1-01-G-0247 (season, Game, league, number) and verifiable online.
- Languages: English and Russian.

## Main pages
- [Home]({url("en","index")}): what the League is and how to join
- [Games & calendar]({url("en","games")}): season structure, next Game, past results
- [FPL Rating]({url("en","rating")}): rankings of face painters by league
- [Gallery]({url("en","gallery")}): judged face painting works
- [Find an artist]({url("en","find")}): face painters taking bookings
- [Rules & FAQ]({url("en","rules")}): rules in plain words
- [Certificate check]({url("en","diploma")}): verify a certificate number
- [About]({url("en","about")}): history, judges, organizer

## Russian version
- [Главная]({url("ru","index")})
''')

if __name__ == '__main__':
    relayout()
    for p in PAGES:
        process(f'{D}/{p}.html', 'en', p)
        process(f'{D}/ru/{p}.html', 'ru', p)
    assets(); crawler_files()
    print('ok', sorted(os.listdir(D)))

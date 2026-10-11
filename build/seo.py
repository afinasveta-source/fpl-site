# SEO-слой сайта FPL: английский — основная версия в корне, русский — в /ru/.
# Запускать после build_site.py и i18n/build_en.py.
import os, re, json, shutil, html
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # build/
from paths import SRC, DIST, I18N, PRIVACY, OG

O = SRC
D = DIST
DOMAIN = 'https://facepaintingleague.com'
PAGES = ['index', 'games', 'rating', 'master', 'gallery', 'find', 'diploma', 'rules', 'about', 'privacy']

def url(lang, p):
    base = DOMAIN + ('/ru/' if lang == 'ru' else '/')
    return base if p == 'index' else base + p + '.html'

META = {
 'en': {
  'index':  ('Face Painting League — online face painting competition', 'An online league for face painters from any country: a new brief every round, professional judges, leagues, a public rating and verifiable certificates.'),
  'games':  ('Games & calendar — Face Painting League', 'Season 1 of Face Painting League: three Games and a Super Final, with short challenges in between. See what is inside the next Game and how to join.'),
  'rating': ('Face painter rankings — FPL Rating', 'The official FPL Rating of face painters, updated after every Game. It weighs opponent strength and sets the Bronze, Silver and Gold leagues.'),
  'master': ('Anna Petrova — face painter profile | FPL', 'Face painter profile on Face Painting League: FPL Rating, league, awards, judged works from every Game and verifiable certificates.'),
  'gallery':('Face painting gallery — works from FPL Games', 'Face painting works by league artists from every Game and round. Filter by Game, round, league and TOP WORK picks chosen by the judges.'),
  'find':   ('Find a face painter — FPL artists taking bookings', 'Hire a face painter whose work has been scored by professional judges. Search FPL artists by city and see their rating, awards and works.'),
  'diploma':('Certificate check — Face Painting League', 'Verify a Face Painting League certificate by its number (FPL-S1-01-0247) or QR code: who it was issued to, for which Game and with what result.'),
  'rules':  ('Rules & FAQ — Face Painting League', 'The Face Painting League rules in plain words: how to join, submit a work, how judging, rating and leagues work, certificates and the Super Final.'),
  'privacy':('Privacy policy — Face Painting League', 'How Face Painting League processes the personal data of participants and website visitors: what we collect, why, where it is stored and how to exercise your rights.'),
  'about':  ('About Face Painting League by MAGFACE', 'Face Painting League is an online league for face painters by MAGFACE, grown out of seven years of face painting marathons with 1,400+ artists.'),
 },
 'ru': {
  'index':  ('Face Painting League — онлайн-лига аквагримёров', 'Онлайн-лига для мастеров аквагрима из любой страны: новое задание каждый тур, профессиональное жюри, лиги, публичный рейтинг и проверяемые дипломы.'),
  'games':  ('Игры и календарь — Face Painting League', 'Сезон 1 Face Painting League: три Игры и Суперфинал, между Играми — короткие челленджи. Что внутри следующей Игры и как в неё попасть.'),
  'rating': ('Рейтинг мастеров аквагрима — FPL Rating', 'Официальный рейтинг FPL. Обновляется после каждой Игры с учётом силы соперников и распределяет мастеров по лигам Bronze, Silver и Gold.'),
  'master': ('Анна Петрова — профиль мастера аквагрима | FPL', 'Профиль мастера в Face Painting League: рейтинг FPL, лига, награды, работы из всех Игр, оценённые жюри, и проверяемые дипломы.'),
  'gallery':('Галерея аквагрима — работы участников FPL', 'Работы мастеров лиги из всех Игр и туров. Фильтры по Игре, туру, лиге и отметке TOP WORK — лучшим работам по выбору жюри.'),
  'find':   ('Найти мастера аквагрима — мастера FPL', 'Закажите аквагрим у мастера, чьи работы оценены профессиональным жюри. Поиск мастеров лиги по городу, их рейтинг, награды и работы.'),
  'diploma':('Проверка диплома — Face Painting League', 'Проверьте диплом Face Painting League по номеру (FPL-S1-01-0247) или QR-коду: кому, за какую Игру и с каким результатом он выдан.'),
  'rules':  ('Правила и вопросы — Face Painting League', 'Правила лиги простыми словами: как участвовать и сдать работу, как устроены оценка, рейтинг и лиги, диплом и Суперфинал.'),
  'privacy':('Политика конфиденциальности — Face Painting League', 'Как Face Painting League обрабатывает персональные данные участников и посетителей сайта: что собираем, зачем, где храним и как реализовать свои права.'),
  'about':  ('О лиге — Face Painting League by MAGFACE', 'Face Painting League — онлайн-лига аквагримёров от MAGFACE. Выросла из семи лет марафонов по аквагриму, в которых участвовали 1400+ мастеров.'),
 }
}
CRUMB = {'en': {'index':'Home','games':'Games','rating':'Rating','master':'Artist','gallery':'Gallery','find':'Find an artist','diploma':'Certificate check','rules':'Rules','about':'About','privacy':'Privacy policy'},
         'ru': {'index':'Главная','games':'Игры','rating':'Рейтинг','master':'Мастер','gallery':'Галерея','find':'Найти мастера','diploma':'Проверка диплома','rules':'Правила','about':'О лиге','privacy':'Политика конфиденциальности'}}
PAGETYPE = {'index':'WebPage','games':'CollectionPage','rating':'CollectionPage','master':'ProfilePage','gallery':'CollectionPage',
            'find':'CollectionPage','diploma':'WebPage','rules':'FAQPage','about':'AboutPage','privacy':'WebPage'}
ORG_DESC = {'en':'Online league for face painters by MAGFACE: Games with judged rounds, leagues, an FPL Rating and verifiable certificates.',
            'ru':'Онлайн-лига аквагримёров от MAGFACE: Игры с оценкой жюри, лиги, рейтинг FPL и проверяемые дипломы.'}

def org():
    return {"@type":"Organization","@id":DOMAIN+"/#org","name":"Face Painting League","alternateName":"FPL",
            "url":DOMAIN+"/","logo":DOMAIN+"/assets/logo-fpl.png",
            "brand":{"@type":"Brand","name":"MAGFACE"},
            "description":ORG_DESC['en']}

def strip(s): return html.unescape(re.sub(r'<[^>]+>','',s)).strip()

def jsonld(lang, p, s):
    title, desc = META[lang][p]
    g = [org()]
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
    if p == 'master':
        # пример: на сервере данные мастера подставляются из базы
        page["mainEntity"] = {"@type":"Person","name":"Anna Petrova" if lang=='en' else "Анна Петрова",
            "jobTitle":"Face painter" if lang=='en' else "Мастер аквагрима",
            "address":{"@type":"PostalAddress","addressLocality":"Saint Petersburg" if lang=='en' else "Санкт-Петербург","addressCountry":"RU"},
            "memberOf":{"@id":DOMAIN+"/#org"}}
    if p == 'about':
        page["about"] = {"@id":DOMAIN+"/#org"}
    g.append(page)
    return json.dumps({"@context":"https://schema.org","@graph":g}, ensure_ascii=False, indent=1)

def head_block(lang, p, s):
    title, desc = META[lang][p]
    og_img = DOMAIN + f'/assets/og-{lang}.png'
    alt = [f'<link rel="alternate" hreflang="en" href="{url("en",p)}">',
           f'<link rel="alternate" hreflang="ru" href="{url("ru",p)}">',
           f'<link rel="alternate" hreflang="x-default" href="{url("en",p)}">']
    tags = [
     f'<title>{html.escape(title)}</title>',
     f'<meta name="description" content="{html.escape(desc)}">',
     f'<link rel="canonical" href="{url(lang,p)}">', *alt,
     '<meta name="robots" content="index,follow,max-image-preview:large">',
     '<meta name="theme-color" content="#1E1B18">',
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
    shutil.copytree(O + '/assets/fonts', D + '/assets/fonts', dirs_exist_ok=True)
    if os.path.isdir(O + '/assets/img'): shutil.copytree(O + '/assets/img', D + '/assets/img', dirs_exist_ok=True)
    # файлы подтверждения для Google Search Console / Яндекс Вебмастера — в корень сайта
    for f in os.listdir(O + '/assets/verify'): shutil.copy(O + '/assets/verify/' + f, D + '/' + f)
    open(D + '/assets/favicon.svg', 'w').write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1E1B18"/>'
        '<text x="32" y="41" text-anchor="middle" font-family="Arial Black,Arial,sans-serif" font-weight="900" font-size="22" fill="#F2601F">FPL</text></svg>')
    for f in ('og-en.png', 'og-ru.png'):
        src = os.path.join(OG, f)
        if os.path.exists(src): shutil.copy(src, D + '/assets/' + f)

def crawler_files():
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for p in PAGES:
        for lang in ('en', 'ru'):
            sm.append(f'  <url><loc>{url(lang,p)}</loc>'
                      f'<xhtml:link rel="alternate" hreflang="en" href="{url("en",p)}"/>'
                      f'<xhtml:link rel="alternate" hreflang="ru" href="{url("ru",p)}"/>'
                      f'<xhtml:link rel="alternate" hreflang="x-default" href="{url("en",p)}"/></url>')
    sm.append('</urlset>')
    open(D + '/sitemap.xml', 'w').write('\n'.join(sm) + '\n')
    open(D + '/robots.txt', 'w').write(f'''# Face Painting League
User-agent: *
Allow: /
Disallow: /api/
Disallow: /account/

# Поисковые и ИИ-роботы: доступ открыт явно
User-agent: Googlebot
Allow: /
User-agent: Bingbot
Allow: /
User-agent: YandexBot
Allow: /
User-agent: GPTBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: Applebot-Extended
Allow: /

Sitemap: {DOMAIN}/sitemap.xml
''')
    open(D + '/llms.txt', 'w').write(f'''# Face Painting League (FPL)

> Face Painting League (FPL) is an online league for face painters, run by MAGFACE. Artists from any country take part in online Games made of judged rounds: each round has a new brief, works are scored anonymously by professional judges, and every artist gets an FPL Rating that places them into the Bronze, Silver or Gold league. A season has three Games and a Super Final, with short open challenges in between. Artists who submit all works on time receive a numbered, verifiable certificate.

Key facts:
- Organizer: MAGFACE, after seven years of face painting marathons (1,400+ artists, 30,000+ works).
- Season 1: three Games and a Super Final. The first Game is free for new participants.
- Judging: anonymous; head-to-head or by criteria depending on the round. TOP WORK marks the best works of each round.
- Certificates: numbered FPL-S1-01-0247 (season, Game, number) and verifiable online.
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

# Страница «Пожелания лиге» (анонимная обратная связь) — собирается так же, как политика (build/privacy/assemble.py):
# оболочка страницы «О лиге» (шапка, меню, подвал) + свой текст и стили из этой папки.
# RU: python3 build/feedback/assemble.py → src/fpl-feedback.html. EN собирается в i18n/build_en.py из готовой en/about.html.
# Форма шлёт POST /kabinet/api/public/feedback (кабинет на том же домене); скрипт формы — внутри ru.html / en.html.
import re
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # build/
from paths import SRC, FEEDBACK
O=SRC; P=FEEDBACK
css=open(P+'/style.css',encoding='utf-8').read()
def make(shell, body, title):
    s=re.sub(r'<style>.*?</style>',lambda m:'<style>\n'+css+'\n</style>',shell,count=1,flags=re.S)
    s=re.sub(r'<title>.*?</title>',f'<title>{title}</title>',s,count=1)
    s=s.replace(' aria-current="page"','')
    a=re.search(r'<section[^>]*class="heroC abhero"',s).start(); b=re.search(r'[ \t]*<footer class="site-footer">',s).start()
    s=s[:a]+body.lstrip()+'\n'+s[b:]
    s=s.replace('<!-- О ЛИГЕ: ШАПКА -->','<!-- ПОЖЕЛАНИЯ -->')
    # ссылка на эту страницу в подвале — текущая
    s=re.sub(r'<a href="((?:fpl-)?feedback\.html)">',r'<a aria-current="page" href="\1">',s)
    return s
if __name__=='__main__':
    sh=open(O+'/fpl-about.html',encoding='utf-8').read()
    open(O+'/fpl-feedback.html','w',encoding='utf-8').write(make(sh,open(P+'/ru.html',encoding='utf-8').read(),'Пожелания лиге · FPL'))
    print('ok')

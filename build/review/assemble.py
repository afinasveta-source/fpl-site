# Страница «Разбор от судьи» (платный аудиоразбор, решение 13.10) — собирается как «Пожелания лиге» (build/feedback):
# оболочка страницы «О лиге» + свой текст и стили. RU: python3 build/review/assemble.py → src/fpl-review.html.
# EN собирается в i18n/build_en.py из готовой en/about.html. Форма шлёт POST /kabinet/api/public/review-order.
import re
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # build/
from paths import SRC, FEEDBACK, REVIEW
O=SRC; P=REVIEW
css=open(FEEDBACK+'/style.css',encoding='utf-8').read()+'\n'+open(P+'/style.css',encoding='utf-8').read()
def make(shell, body, title):
    s=re.sub(r'<style>.*?</style>',lambda m:'<style>\n'+css+'\n</style>',shell,count=1,flags=re.S)
    s=re.sub(r'<title>.*?</title>',f'<title>{title}</title>',s,count=1)
    s=s.replace(' aria-current="page"','')
    a=re.search(r'<section[^>]*class="heroC abhero"',s).start(); b=re.search(r'[ \t]*<footer class="site-footer">',s).start()
    s=s[:a]+body.lstrip()+'\n'+s[b:]
    s=s.replace('<!-- О ЛИГЕ: ШАПКА -->','<!-- РАЗБОР ОТ СУДЬИ -->')
    return s
if __name__=='__main__':
    sh=open(O+'/fpl-about.html',encoding='utf-8').read()
    open(O+'/fpl-review.html','w',encoding='utf-8').write(make(sh,open(P+'/ru.html',encoding='utf-8').read(),'Разбор от судьи · FPL'))
    print('ok')

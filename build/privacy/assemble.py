import re
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # build/
from paths import SRC, DIST, I18N, PRIVACY, OG
O=SRC; P=PRIVACY
css=open(P+'/style.css').read()
def make(shell, body, title):
    s=re.sub(r'<style>.*?</style>','<style>\n'+css+'\n</style>',shell,count=1,flags=re.S)
    s=re.sub(r'<title>.*?</title>',f'<title>{title}</title>',s,count=1)
    s=s.replace(' aria-current="page"','')
    a=re.search(r'<section[^>]*class="heroC abhero"',s).start(); b=re.search(r'[ \t]*<footer class="site-footer">',s).start()
    # оставить комментарий-маркер перед шапкой
    s=s[:a]+body.lstrip()+'\n'+s[b:]
    s=s.replace('<!-- О ЛИГЕ: ШАПКА -->','<!-- ПОЛИТИКА -->')
    return s
if __name__=='__main__':
    sh=open(O+'/fpl-about.html',encoding='utf-8').read()
    open(O+'/fpl-privacy.html','w',encoding='utf-8').write(make(sh,open(P+'/ru.html').read(),'Политика конфиденциальности · FPL'))
    print('ok')

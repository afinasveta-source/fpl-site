import re,json,os
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # build/
from paths import SRC, DIST, I18N, PRIVACY, FEEDBACK, REVIEW, OG
import importlib.util
from bs4 import BeautifulSoup
I=I18N
D=DIST
PAGES=['index','games','rating','master','gallery','find','diploma','rules','about','privacy','feedback','review']
CY=re.compile('[А-Яа-яЁё]')
T={}
for i in (1,2,3): T.update(json.load(open(f'{I}/en{i}.json',encoding='utf-8')))
J=json.load(open(f'{I}/jsmap.json',encoding='utf-8'))
EXTRA=json.load(open(f'{I}/extra.json',encoding='utf-8')) if os.path.exists(f'{I}/extra.json') else {}
T.update(EXTRA.get('html',{}))
def leaves(soup):
    res=[]
    for el in soup.find_all(True):
        if el.name in('script','style','svg') or el.find_parent(['script','style','svg']): continue
        if not CY.search(el.decode_contents()): continue
        if [c for c in el.find_all(True) if c.name not in('span','b','i','small','strong','em','br','a','sup')]: continue
        res.append(el)
    ids=set(id(e) for e in res)
    return [e for e in res if not any(id(p) in ids for p in e.parents)]
LANG_RU='''<li><button type="button" data-lang="{c}" data-short="{s}" disabled class="soon">{n}<small>{soon}</small></button></li>'''
def lang_menu(s,page,en):
    other=[('de','DE','Deutsch'),('es','ES','Español'),('fr','FR','Français'),('zh','中文','中文'),('ja','日本語','日本語')]
    ru_href=('../' if en else '')+page+'.html'; en_href=(page+'.html') if en else ('en/'+page+'.html')
    items=(f'<li><button type="button" data-lang="ru" data-short="RU" data-href="{ru_href}"'+('' if en else ' class="on" aria-current="true"')+'>Русский</button></li>'
           f'<li><button type="button" data-lang="en" data-short="EN" data-href="{en_href}"'+(' class="on" aria-current="true"' if en else '')+'>English</button></li>'
           + ''.join(LANG_RU.format(c=c,s=sh,n=n,soon='soon' if en else 'скоро') for c,sh,n in other))
    s=re.sub(r'<ul class="lang-list" hidden(?:="")?>.*?</ul>',f'<ul class="lang-list" hidden>{items}</ul>',s,flags=re.S)
    s=re.sub(r'<span data-lang-label(?:="")?>(RU|EN)</span>','<span data-lang-label>'+('EN' if en else 'RU')+'</span>',s)
    css='.lang-list button.soon{opacity:.45; cursor:default; display:flex; justify-content:space-between; gap:10px} .lang-list button.soon small{font:500 11px var(--f-body)} .lang-list button.soon:hover{background:none}'
    if 'button.soon' not in s: s=s.replace('</style>',css+'\n</style>',1)
    js='''<script>
(function(){ var l=document.querySelector('.lang-list'); if(!l) return;
  l.addEventListener('click',function(e){ var b=e.target.closest('button'); if(!b) return; e.stopPropagation();
    if(b.disabled) return; var h=b.getAttribute('data-href'); if(h && !b.classList.contains('on')) location.href=h; else l.hidden=true; },true);
})();
</script>'''
    if "getAttribute('data-href')" not in s: s=s.replace('</body>',js+'\n</body>',1)
    return s
ASSEMBLED={'privacy':(PRIVACY,'Privacy policy · FPL'),'feedback':(FEEDBACK,'Ideas for the league · FPL'),'review':(REVIEW,'Review by a judge · FPL')}
def build():
    os.makedirs(D+'/en',exist_ok=True)
    miss=[]
    for p in PAGES:
        if p in ASSEMBLED:
            # страницы из оболочки «О лиге» + свой текст (build/privacy, build/feedback): EN — из готовой en/about.html
            folder,title=ASSEMBLED[p]
            spec=importlib.util.spec_from_file_location('assemble_'+p,os.path.join(folder,'assemble.py'))
            assemble=importlib.util.module_from_spec(spec); spec.loader.exec_module(assemble)
            ru=lang_menu(open(f'{D}/{p}.html',encoding='utf-8').read(),p,False); open(f'{D}/{p}.html','w',encoding='utf-8').write(ru)
            sh=open(f'{D}/en/about.html',encoding='utf-8').read()
            out=assemble.make(sh,open(assemble.P+'/en.html',encoding='utf-8').read(),title)
            out=lang_menu(out,p,True); open(f'{D}/en/{p}.html','w',encoding='utf-8').write(out)
            continue
        raw=open(f'{D}/{p}.html',encoding='utf-8').read()
        ru=lang_menu(raw,p,False); open(f'{D}/{p}.html','w',encoding='utf-8').write(ru)
        s=ru
        # JS-строки
        def fixjs(m):
            sc=m.group(0)
            for a,b in sorted(J.get(p,{}).items(), key=lambda x:-len(x[0])):
                sc=sc.replace("'"+a+"'","'"+b+"'")
            for a,b in EXTRA.get('js',{}).get(p,{}).items(): sc=sc.replace(a,b)
            return sc
        s=re.sub(r'<script>.*?</script>',fixjs,s,flags=re.S)
        soup=BeautifulSoup(s,'html.parser')
        for e in leaves(soup):
            k=e.decode_contents().strip()
            if k in T:
                e.clear(); e.append(BeautifulSoup(T[k],'html.parser'))
            else: miss.append((p,k[:80]))
        for e in soup.find_all(True):
            for a in('placeholder','aria-label','title','alt'):
                v=e.get(a)
                if v and CY.search(v):
                    if '@'+v in T: e[a]=T['@'+v][1:]
                    else: miss.append((p,'@'+v))
        if soup.html: soup.html['lang']='en'
        out=str(soup)
        out=lang_menu(out,p,True)
        for a,b in list(EXTRA.get('raw',{}).get(p,{}).items())+list(EXTRA.get('raw',{}).get('_all',{}).items()): out=out.replace(a,b)
        open(f'{D}/en/{p}.html','w',encoding='utf-8').write(out)
        left=[]
        for sc in re.findall(r'<script>(.*?)</script>',out,re.S):
            sc=re.sub(r'//[^\n]*','',sc); left+=re.findall(r"'[^'\n]*[А-Яа-яЁё][^'\n]*'",sc)
        txt=re.sub(r'<(script|style)\b.*?</\1>','',out,flags=re.S)
        vis=[t for t in re.findall(r'>([^<]*[А-Яа-яЁё][^<]*)<',txt)]
        if left or vis: print('LEFT',p,'js:',left[:8],'html:',[v.strip()[:60] for v in vis][:8])
    print('missing',len(miss)); [print(m) for m in miss[:20]]
build()

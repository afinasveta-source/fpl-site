import re,os,shutil
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # build/
from paths import SRC, DIST, I18N, PRIVACY, OG
O=SRC; D=DIST
M={'fpl-site-pro-ink.html':'index.html','fpl-gallery.html':'gallery.html','fpl-find.html':'find.html','fpl-rating.html':'rating.html','fpl-master.html':'master.html','fpl-games.html':'games.html','fpl-diploma.html':'diploma.html','fpl-rules.html':'rules.html','fpl-about.html':'about.html','fpl-privacy.html':'privacy.html'}
if os.path.isdir(D): shutil.rmtree(D)
os.makedirs(D+'/assets')
shutil.copy(O+'/assets/site.css',D+'/assets/site.css')
shutil.copytree(O+'/assets/fonts',D+'/assets/fonts')
for src,dst in M.items():
    s=open(f'{O}/{src}',encoding='utf-8').read()
    for a,b in M.items(): s=s.replace(f'"{a}"',f'"{b}"').replace(f'"{a}#',f'"{b}#').replace(f"'{a}",f"'{b}").replace(f'"{a}?',f'"{b}?')
    # убрать устаревший код старой формы проверки диплома со всех страниц, кроме главной
    if dst!='index.html':
        s=re.sub(r"  // проверка диплома \(в прототипе — один пример\)\n  var f=document.getElementById\('verifyForm'\); if\(f\)\{.*?\n  \}\n","",s,flags=re.S)
    open(f'{D}/{dst}','w',encoding='utf-8').write(s)
# проверка ссылок и якорей
bad=[]
for dst in M.values():
    s=open(f'{D}/{dst}',encoding='utf-8').read()
    for h in re.findall(r'href="([^"]+)"',s):
        if h.startswith(('http','mailto:','#p','#crystal')) or h=='#': continue
        f,_,a=h.partition('#'); f=f.split('?')[0] or dst
        if not os.path.exists(f'{D}/{f}'): bad.append((dst,h,'нет файла')); continue
        if a and f'id="{a}"' not in open(f'{D}/{f}',encoding='utf-8').read(): bad.append((dst,h,'нет якоря'))
    for old in re.findall(r'fpl-[a-z-]+\.html',s): bad.append((dst,old,'старое имя'))
print('проблем:',len(bad)); [print(*b) for b in bad]
print(sorted(os.listdir(D)))

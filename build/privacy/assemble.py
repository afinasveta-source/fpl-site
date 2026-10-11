import re
O='/mnt/user-data/outputs'; P='/tmp/claude-0/-home-claude/d727aedf-8651-581c-b2f6-7103a986585f/scratchpad/privacy'
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

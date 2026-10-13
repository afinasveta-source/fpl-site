"""Экраны на больших данных (Playwright, 390 и 1280): ошибки в консоли, горизонтальная прокрутка, время загрузки.

    python -m sim.screens <порт> <папка для снимков> <id Игры> <email участницы> <email судьи>
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

PW = 'Sim-test-password-123!'


def main():
    port, out, eid, part, judge = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    B = f'http://127.0.0.1:{port}'
    report = {'errors': [], 'pages': []}

    def watch(p, who):
        p.on('console', lambda m: report['errors'].append(f'{who} console: {m.text[:200]}') if m.type == 'error' else None)
        p.on('pageerror', lambda e: report['errors'].append(f'{who} pageerror: {str(e)[:200]}'))
        p.on('response', lambda r: report['errors'].append(f'{who} HTTP {r.status} {r.url}') if r.status >= 400 and '/web-auth/me' not in r.url else None)

    def login(ctx, email, who):
        p = ctx.new_page()
        watch(p, who)
        p.goto(B + '/')
        p.fill('#email', email)
        p.fill('#password', PW)
        p.click('#f-login button[type=submit]')
        p.wait_for_selector('.rail', state='attached')
        return p

    def visit(p, path, name, width, wait='#main h1'):
        t = time.perf_counter()
        p.goto(B + path)
        try:
            p.wait_for_selector(wait, timeout=30000)
        except Exception as exc:
            report['errors'].append(f'{name} {width}: не открылась ({exc.__class__.__name__})')
        p.wait_for_timeout(300)
        dt = time.perf_counter() - t
        sw, cw = p.evaluate('document.documentElement.scrollWidth'), p.evaluate('document.documentElement.clientWidth')
        if sw > cw + 1:
            report['errors'].append(f'{name} {width}: горизонтальная прокрутка {sw} > {cw}')
        p.screenshot(path=f'{out}/{width}-{name}.png', full_page=False)
        report['pages'].append({'page': name, 'width': width, 'seconds': round(dt, 2)})

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for width in (390, 1280):
            ctx = br.new_context(viewport={'width': width, 'height': 900})
            o = login(ctx, 'org@example.com', 'org')
            rid = None
            for path, name in ((f'/org', 'org-home'), (f'/org/games/{eid}', 'org-game'), (f'/org/games/{eid}/people', 'org-people-200'),
                               (f'/org/games/{eid}/results', 'org-results'), ('/org/people', 'org-all-people')):
                visit(o, path, name, width)
            links = o.evaluate("Array.from(document.querySelectorAll('[data-href]')).map(e => e.getAttribute('data-href'))")
            o.goto(B + f'/org/games/{eid}')
            o.wait_for_selector('#main h1')
            hrefs = o.evaluate("Array.from(document.querySelectorAll('[data-href]')).map(e => e.getAttribute('data-href'))")
            rounds = [h for h in hrefs if h and h.startswith('/org/rounds/') and h.count('/') == 3]
            if rounds:
                visit(o, rounds[0], 'org-round', width)
                visit(o, rounds[0] + '/judging', 'org-judging', width)
            ctx2 = br.new_context(viewport={'width': width, 'height': 900})
            p = login(ctx2, part, 'participant')
            for path, name in (('/', 'p-home'), (f'/games/{eid}', 'p-game'), ('/achievements', 'p-achievements'), ('/notifications', 'p-notes')):
                visit(p, path, name, width)
            ctx3 = br.new_context(viewport={'width': width, 'height': 900})
            j = login(ctx3, judge, 'judge')
            visit(j, '/judging', 'j-home', width)
            sids = j.evaluate("Array.from(document.querySelectorAll('[data-href]')).map(e => e.getAttribute('data-href')).filter(h => h && h.startsWith('/judging/'))")
            if sids:
                visit(j, sids[0], 'j-stream', width)
            for c in (ctx, ctx2, ctx3):
                c.close()
        br.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()

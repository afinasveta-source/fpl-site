"""Независимая сверка: пересчёт по правилам (документы проекта, решения 03–13.10) из сырых данных базы —
голоса, оценки, статусы, сроки. Модули расчёта кабинета (kabinet.*.compute) здесь НЕ используются.
"""
import math
from collections import defaultdict
from datetime import timedelta


def hu(x, d=0):
    q = 10 ** d
    return math.floor(x * q + 0.5) / q


# ---------------------------------------------------------------- Брэдли–Терри (своя реализация)

def bt(votes):
    """votes: [(a, b, winner, for_a, for_b)]. Одна условная победа и одно поражение против силы 1.
    Возвращает {работа: доля обыграть среднюю (геом.) работу}."""
    opp = defaultdict(list)
    w = defaultdict(float)
    for a, b, win, fa, fb in votes:
        if fa:
            opp[a].append(b)
            w[a] += win == a
        if fb:
            opp[b].append(a)
            w[b] += win == b
    items = list(opp)
    s = {x: 1.0 for x in set(items) | {o for t in items for o in opp[t]}}
    for _ in range(100000):
        new = {}
        for i in items:
            den = sum(1 / (s[i] + s[j]) for j in opp[i]) + 2 / (s[i] + 1)
            new[i] = (w[i] + 1) / den
        diff = max((abs(math.log(new[i] / s[i])) for i in items), default=0)
        s.update(new)
        if diff < 1e-13:
            break
    vals = {i: s[i] for i in items}
    if not vals:
        return {}
    g = math.exp(sum(math.log(v) for v in vals.values()) / len(vals))
    return {i: v / (v + g) for i, v in vals.items()}


def score_of_share(sh):
    return int(math.floor(1 + 99 * sh + 0.5))


# ---------------------------------------------------------------- тур

def stream_data(w, st_id):
    targets = {str(r['t']): r for r in w.q('''SELECT t.id AS t, m.event_participant_id AS ep, p.entry_league AS league
FROM evaluation_targets t JOIN evaluation_target_members m ON m.evaluation_target_id=t.id
JOIN event_participants p ON p.id=m.event_participant_id WHERE t.evaluation_stream_id=%s''', (st_id,))}
    res = {str(r['evaluation_target_id']): r for r in w.q('''SELECT * FROM evaluation_results WHERE evaluation_stream_id=%s
AND is_current''', (st_id,))}
    return targets, res


def check_round(w, rnd):
    P = w.p
    no = rnd['no']
    area = f'тур {no}'
    streams = w.q('SELECT * FROM evaluation_streams WHERE round_id=%s AND active', (rnd['id'],))
    rr = {str(r['event_participant_id']): r for r in w.q('''SELECT * FROM round_results WHERE round_id=%s AND is_current''', (rnd['id'],))}
    mism = 0
    for st in streams:
        targets, res = stream_data(w, st['id'])
        cfg = st['configuration'] or {}
        lg = st['league'] or 'all'
        # 1. балл
        if st['judging_method'] == 'pairwise':
            comps = w.q('''SELECT * FROM pairwise_comparisons WHERE evaluation_stream_id=%s AND status='voted' ''', (st['id'],))
            def votes(phases):
                return [(str(c['target_a_id']), str(c['target_b_id']), str(c['winner_target_id']),
                         c['counts_for'] in ('both', 'target_a'), c['counts_for'] in ('both', 'target_b'))
                        for c in comps if c['phase'] in phases]
            key = bt(votes(('regular',)))
            full = bt(votes(('regular', 'tie_break')))
            mine = {t: score_of_share(full[t]) if t in full else None for t in targets}
            # каждая пара у судьи — один раз; у судьи работа встречается per_target раз
            per = defaultdict(lambda: defaultdict(int))
            pairs = defaultdict(set)
            for c in w.q('''SELECT * FROM pairwise_comparisons WHERE evaluation_stream_id=%s AND phase='regular' AND status<>'cancelled' ''', (st['id'],)):
                k = frozenset((str(c['target_a_id']), str(c['target_b_id'])))
                P.check(k not in pairs[c['judge_slot_id']], 'major', area, f'пул {lg}: у судьи повтор пары')
                pairs[c['judge_slot_id']].add(k)
                for t in k:
                    per[c['judge_slot_id']][t] += 1
            n = len(targets)
            for slot, cnt in per.items():
                if cfg.get('regular_closed'):
                    break
                expect = st['comparisons_per_target_per_judge']
                odd = [t for t in targets if cnt.get(t, 0) != expect]
                if n > expect:
                    P.check(not odd, 'minor', area, f'пул {lg}: у судьи {len(odd)} работ встречаются не {expect} раз '
                                                     f'(например {cnt.get(odd[0], 0) if odd else 0})')
        else:
            crit = {str(c['id']): float(c['weight']) for c in w.q('SELECT * FROM evaluation_criteria WHERE evaluation_stream_id=%s', (st['id'],))}
            by = defaultdict(lambda: defaultdict(dict))
            for s in w.q("SELECT * FROM criterion_scores WHERE evaluation_stream_id=%s AND status='valid'", (st['id'],)):
                by[str(s['evaluation_target_id'])][s['judge_slot_id']][str(s['criterion_id'])] = float(s['score'])
                P.check(1 <= float(s['score']) <= 100 and float(s['score']) == int(s['score']), 'critical', area,
                        f'оценка вне 1–100 или дробная: {s["score"]}')
            tw = sum(crit.values())
            key, mine = {}, {}
            for t in targets:
                per_judge = [sum(sc[c] * wt for c, wt in crit.items()) / tw for sc in by[t].values() if set(sc) >= set(crit)]
                v = sum(per_judge) / len(per_judge) if per_judge else None
                key[t] = v
                mine[t] = int(math.floor(v + 0.5)) if v is not None else None
        for t, r in res.items():
            got = float(r['display_score']) if r['display_score'] is not None else None
            if got != mine.get(t):
                mism += 1
                if mism <= 5:
                    P.add('critical', area, f'пул {lg}: балл {got} ≠ пересчёт {mine.get(t)}')
        # 2. кто «остался» (в конкурсе на момент публикации) — у вышедших qualified пусто
        staying = [t for t, r in res.items() if r['qualified'] is not None]
        left = [t for t, r in res.items() if r['qualified'] is None]
        # 3. проход: ровно квота (если не решалось иначе), и прошедшие не слабее непрошедших — кроме групп на границе
        quota = cfg.get('quota')
        adv = [t for t in staying if res[t]['qualified']]
        if quota and quota < len(staying):
            decided = {x for d in cfg.get('admin_decisions', []) for x in d['targets']}
            tbs = {x for tb in cfg.get('tie_breaks', []) for x in tb['targets']}
            P.check(len(adv) == quota or decided or tbs, 'critical', area, f'пул {lg}: прошли {len(adv)}, квота {quota}')
            if len(adv) != quota:
                P.add('note', area, f'пул {lg}: прошли {len(adv)} при квоте {quota} (решения на границе: {len(decided)}, переголосование: {len(tbs)})')
            weakest_in = min((key[t] for t in adv if key.get(t) is not None and t not in decided | tbs), default=None)
            strongest_out = max((key[t] for t in staying if t not in adv and key.get(t) is not None and t not in decided | tbs), default=None)
            if weakest_in is not None and strongest_out is not None:
                P.check(weakest_in >= strongest_out - 1e-12, 'critical', area,
                        f'пул {lg}: не прошла работа сильнее прошедшей ({strongest_out:.4f} > {weakest_in:.4f})')
        # 4. TOP WORK — в каждой лиге по баллу тура, min(10, 20%), равные на границе — все, лига < 5 — нет
        by_league = defaultdict(list)
        for t in staying:
            if mine.get(t) is not None:
                by_league[targets[t]['league']].append(t)
        expect_top = set()
        for league, items in by_league.items():
            n = len(items)
            if n < 5:
                continue
            cut = min(10, n * 20 // 100)
            ordered = sorted(items, key=lambda t: -(key[t] if key[t] is not None else -1))
            if cut <= 0:
                continue
            border_key = key[ordered[cut - 1]]
            expect_top |= {t for t in items if key[t] >= border_key - 1e-12}
        got_top = {t for t in targets if rr.get(str(targets[t]['ep'])) and rr[str(targets[t]['ep'])]['top_work']}
        if got_top != expect_top:
            P.add('critical', area, f'пул {lg}: TOP WORK расходится: лишние {len(got_top - expect_top)}, нет {len(expect_top - got_top)}')
        # 5. итог тура участницы = итог пула; лига; статус после тура
        for t, r in res.items():
            ep = str(targets[t]['ep'])
            x = rr.get(ep)
            if not P.check(x is not None, 'critical', area, f'нет итога тура у участницы {ep}'):
                continue
            P.check((float(x['display_score']) if x['display_score'] is not None else None) ==
                    (float(r['display_score']) if r['display_score'] is not None else None), 'critical', area, 'итог тура ≠ итог пула')
            P.check(x['league'] == targets[t]['league'], 'major', area, f"лига в итоге тура {x['league']} ≠ {targets[t]['league']}")
            P.check(x['advanced'] == r['qualified'], 'major', area, 'проход в итоге тура ≠ в итоге пула')
    # 6. непрошедшие в конкурсе — «выбыла по судейству»
    for ep, x in rr.items():
        if x['advanced'] is False:
            row = w.q1('SELECT competition_status, elimination_reason FROM event_participants WHERE id=%s', (ep,))
            P.check(row['competition_status'] in ('eliminated', 'diploma_only') or row['competition_status'] == 'disqualified',
                    'critical', area, f"не прошла, но статус {row['competition_status']}")
    # 7. каждая сданная вовремя работа в конкурсе попала в судейство
    sub = w.q('''SELECT s.event_participant_id AS ep, s.is_on_time, p.competition_status, p.registration_status
FROM submissions s JOIN participant_assignments pa ON pa.id=s.participant_assignment_id
JOIN event_participants p ON p.id=s.event_participant_id WHERE pa.assignment_id=%s AND s.latest_version_id IS NOT NULL''', (rnd['assignment_id'],))
    judged = {str(r['ep']) for r in w.q('''SELECT m.event_participant_id AS ep FROM evaluation_target_members m
JOIN evaluation_targets t ON t.id=m.evaluation_target_id JOIN evaluation_streams s ON s.id=t.evaluation_stream_id WHERE s.round_id=%s''', (rnd['id'],))}
    for s in sub:
        if s['is_on_time'] and str(s['ep']) not in judged and s['registration_status'] not in ('withdrawn', 'cancelled') \
                and s['competition_status'] == 'active':
            P.add('major', area, f"работа сдана вовремя, но не судилась: статус {s['competition_status']}")
    late_judged = [s for s in sub if s['is_on_time'] is False and str(s['ep']) in judged]
    P.check(not late_judged, 'critical', area, f'судились работы, сданные после срока: {len(late_judged)}')
    print(f'   oracle {area}: {len(streams)} pools checked, score mismatches {mism}')


# ---------------------------------------------------------------- финал: подстроенные равенства

def engineer_final(w, rnd):
    """Оценки финала так, чтобы проверить равенства: в одной лиге — равный итог и равный финал (решает организатор),
    в другой — равный итог при разном финале (выше финал). Возвращает {i участницы: оценка всех судей}."""
    scores = path_scores(w)
    forced = {}
    finalists = [p for p in w.part if p.get('ep_id') and w.q1(
        "SELECT competition_status FROM event_participants WHERE id=%s", (p['ep_id'],))['competition_status'] == 'active']
    w.engineered = []
    for p in finalists:
        forced[p['i']] = int(max(1, min(70, round(55 + 8 * p['skill']))))
    for lg, mode in (('gold', 'equal'), ('silver', 'final'), ('bronze', 'equal')):
        group = [p for p in finalists if p['league'] == lg and len(scores.get(p['ep_id'], {})) == 4]
        found = None
        for a in group:
            for b in group:
                if a['i'] >= b['i']:
                    continue
                pa, pb = sum(scores[a['ep_id']].values()) / 4, sum(scores[b['ep_id']].values()) / 4
                d = pa - pb
                if mode == 'equal' and d == 0:
                    found = (a, b, 0)
                if mode == 'final' and d != 0 and abs(d * 2 / 3 - round(d * 2 / 3)) < 1e-9 and abs(d) <= 6:
                    found = (a, b, int(round(d * 2 / 3)))
                if found:
                    break
            if found:
                break
        if not found:
            w.p.add('note', 'финал', f'{lg}: не нашлось пары для проверки равенства ({mode})')
            continue
        a, b, k = found
        top = 99 - max(0, k)
        forced[a['i']], forced[b['i']] = top, top + k     # итог равен: 0.4·pa + 0.6·fa = 0.4·pb + 0.6·fb
        w.engineered.append((lg, mode, a['ep_id'], b['ep_id']))
        print(f'   final tie engineered in {lg}: {mode}')
    return forced


def path_scores(w):
    out = defaultdict(dict)
    for r in w.q('''SELECT rr.event_participant_id AS ep, r.round_no, rr.display_score, rr.advanced FROM round_results rr
JOIN rounds r ON r.id=rr.round_id WHERE rr.event_id=%s AND rr.is_current AND rr.status='published' ''', (w.event,)):
        if r['advanced'] is not None and r['display_score'] is not None and r['round_no'] <= 4:
            out[str(r['ep'])][r['round_no']] = float(r['display_score'])
    return out


# ---------------------------------------------------------------- итоги Игры

GRID = {'places': {'gold': [20, 15, 12], 'silver': [12, 10, 8], 'bronze': [8, 6, 5]}, 'top10': 8, 'top25': 5,
        'completion': 3, 'top_work': 1}


def check_game(w):
    P = w.p
    area = 'итоги Игры'
    eid = w.event
    ev = w.q1('SELECT * FROM events WHERE id=%s', (eid,))
    rounds = {r['round_no']: r for r in w.q('SELECT * FROM rounds WHERE event_id=%s', (eid,))}
    variants = defaultdict(dict)
    for v in w.q('''SELECT r.round_no, v.* FROM assignment_variants v JOIN assignments a ON a.id=v.assignment_id
JOIN rounds r ON r.id=a.round_id WHERE r.event_id=%s''', (eid,)):
        lg = ((v['audience_rules'] or {}).get('leagues') or [None])[0]
        variants[v['round_no']][lg] = v
    eps = {str(r['id']): r for r in w.q('''SELECT p.*, u.full_name, u.display_name FROM event_participants p JOIN users u ON u.id=p.user_id
WHERE p.event_id=%s''', (eid,))}
    rr = defaultdict(dict)
    tops = defaultdict(int)
    for r in w.q('''SELECT rr.*, r.round_no FROM round_results rr JOIN rounds r ON r.id=rr.round_id WHERE rr.event_id=%s
AND rr.is_current AND rr.status='published' ''', (eid,)):
        if r['advanced'] is not None:
            rr[str(r['event_participant_id'])][r['round_no']] = float(r['display_score']) if r['display_score'] is not None else None
        tops[str(r['event_participant_id'])] += bool(r['top_work'])
    subs = defaultdict(dict)
    for s in w.q('''SELECT s.event_participant_id AS ep, r.round_no, s.latest_version_id, v.submitted_at, pa.deadline_override
FROM submissions s JOIN participant_assignments pa ON pa.id=s.participant_assignment_id JOIN assignments a ON a.id=pa.assignment_id
JOIN rounds r ON r.id=a.round_id LEFT JOIN submission_versions v ON v.id=s.latest_version_id WHERE r.event_id=%s''', (eid,)):
        if s['latest_version_id']:
            subs[str(s['ep'])][s['round_no']] = s
    first_sub = defaultdict(dict)
    for s in w.q('''SELECT s.event_participant_id AS ep, r.round_no, min(v.submitted_at) AS t FROM submissions s
JOIN participant_assignments pa ON pa.id=s.participant_assignment_id JOIN assignments a ON a.id=pa.assignment_id
JOIN rounds r ON r.id=a.round_id JOIN submission_versions v ON v.submission_id=s.id AND v.submitted_at IS NOT NULL
WHERE r.event_id=%s GROUP BY 1,2''', (eid,)):
        first_sub[str(s['ep'])][s['round_no']] = s['t']

    end = ev['completion_deadline'] or ev['ends_at']
    people = []
    for ep, row in eps.items():
        if row['registration_status'] in ('cancelled', 'pre_registered', 'payment_pending'):
            continue
        mode_withdrawn = row['registration_status'] in ('withdrawn', 'cancelled')
        dq = row['competition_status'] == 'disqualified'
        excl = 'withdrawn' if mode_withdrawn else 'disqualified' if dq else None
        if excl is None and row['elimination_reason'] == 'late':
            excl = 'late'
        if excl is None and row['elimination_reason'] == 'admin':
            excl = 'admin'
        sc = rr.get(ep, {})
        # зачёт: все 5 работ, каждая — до своего срока (личный срок — если продлён); первая отправка вовремя
        on_time = all(no in subs[ep] and first_sub[ep].get(no) is not None and
                      first_sub[ep][no] <= (subs[ep][no]['deadline_override'] or w.deadline_for(no, row['entry_league']))
                      for no in range(1, len(w.rounds) + 1))
        all_sent = all(no in subs[ep] and subs[ep][no]['submitted_at'] <= end for no in range(1, len(w.rounds) + 1))
        people.append({'ep': ep, 'name': row['full_name'], 'league': row['entry_league'], 'scores': sc, 'excl': excl,
                       'counted': on_time and not mode_withdrawn and not dq, 'diploma': all_sent and not dq,
                       'tops': tops.get(ep, 0)})
    # стадия, финалисты, итог
    fmt = getattr(w, 'fmt', {'final': 5, 'path': [1, 2, 3, 4], 'weight': 40})
    FIN, PATH, WT = fmt['final'], fmt['path'], fmt['weight'] / 100
    LAST = FIN if FIN is not None else max(PATH)
    for p in people:
        p['stage'] = max(p['scores']) if p['scores'] else None
        p['finalist'] = LAST in p['scores'] and p['excl'] is None
        if p['excl'] is None and not p['finalist'] and p['stage'] == 1:
            p['excl'] = 'not_qualified_round1'
        if p['finalist']:
            path = [p['scores'][n] for n in PATH if p['scores'].get(n) is not None]
            if FIN is None:
                p['total'] = hu(sum(path) / len(path), 2)
            else:
                f = p['scores'][FIN]
                p['total'] = hu(sum(path) / len(path) * WT + f * (1 - WT), 2) if path and WT else hu(f, 2)
        else:
            p['total'] = None
    ranked = [p for p in people if p['excl'] is None and p['stage'] is not None]

    def k(p):
        if p['finalist']:
            return (0, 0, -p['total'], -(p['scores'][FIN] if FIN is not None else 0))
        return (1, -p['stage'], -p['scores'][p['stage']], 0)
    ranked.sort(key=k)
    prev = None
    for i, p in enumerate(ranked, 1):
        p['overall'] = prev['overall'] if prev and k(prev) == k(p) else i
        prev = p
    decided = {lg: order for lg, order in getattr(w, 'tie_decided', [])}
    for lg in ('gold', 'silver', 'bronze'):
        mem = [p for p in ranked if p['league'] == lg]
        if lg in decided:
            order = decided[lg]
            pos = [i for i, p in enumerate(mem) if p['ep'] in order]
            chosen = sorted([mem[i] for i in pos], key=lambda p: order.index(p['ep']))
            for i, p in zip(pos, chosen):
                mem[i] = p
        prev = None
        for i, p in enumerate(mem, 1):
            same = prev and k(prev) == k(p) and not (lg in decided and prev['ep'] in decided[lg] and p['ep'] in decided[lg])
            p['lrank'] = prev['lrank'] if same else i
            prev = p
        n = len(mem)
        c10 = min(10, n * 20 // 100) if n >= 30 else 0
        c25 = min(25, n * 20 // 100) if n >= getattr(w, 'top25_min', 60) else 0   # в симуляции порог TOP-25 = 60 (формат Игры)
        for p in mem:
            p['top10'] = p['lrank'] <= c10
            p['top25'] = p['lrank'] <= c25
            p['award'] = None
        fin = [p for p in mem if p['finalist']]
        for p in fin:
            if p['lrank'] <= 3 and sum(1 for q in fin if q['lrank'] == p['lrank']) == 1:
                p['award'] = p['lrank']
    for p in people:
        p.setdefault('overall', None)
        p.setdefault('lrank', None)
        p.setdefault('award', None)
        p.setdefault('top10', False)
        p.setdefault('top25', False)
        if p['excl'] == 'disqualified':
            p['pts'] = 0
            continue
        opts = [0]
        if p['award'] and p['league']:
            opts.append(GRID['places'][p['league']][p['award'] - 1])
        if p['top10']:
            opts.append(GRID['top10'])
        if p['top25']:
            opts.append(GRID['top25'])
        if p['counted']:
            opts.append(GRID['completion'])
        p['pts'] = max(opts) + p['tops'] * GRID['top_work']
    # сравнение с опубликованным
    er = {str(r['event_participant_id']): r for r in w.q('''SELECT * FROM event_results WHERE event_id=%s AND is_current''', (eid,))}
    pts = defaultdict(int)
    for t in w.q('SELECT * FROM points_transactions WHERE event_id=%s', (eid,)):
        pts[str(t['user_id'])] += t['lifetime_delta']
    stats = {str(s['user_id']): s['lifetime_points'] for s in w.q('SELECT * FROM participant_stats')}
    certs = defaultdict(list)
    for c in w.q('''SELECT * FROM certificates WHERE event_participant_id IN (SELECT id FROM event_participants WHERE event_id=%s)
AND revoked_at IS NULL''', (eid,)):
        certs[str(c['event_participant_id'])].append(c)
    bad = defaultdict(list)
    for p in people:
        r = er.get(p['ep'])
        uid = str(eps[p['ep']]['user_id'])
        if r is None:
            bad['нет итога'].append(p['name'])
            continue
        fs = float(r['final_score']) if r['final_score'] is not None else None
        if fs != p['total'] and p['finalist']:
            bad['итог'].append(f"{p['name']}: {fs} ≠ {p['total']}")
        if r['league_rank'] != p['lrank']:
            bad['место в лиге'].append(f"{p['name']} ({p['league']}): {r['league_rank']} ≠ {p['lrank']}")
        if r['overall_rank'] != p['overall']:
            bad['общий список'].append(f"{p['name']}: {r['overall_rank']} ≠ {p['overall']}")
        if r['award_place'] != p['award']:
            bad['призовое место'].append(f"{p['name']} ({p['league']}): {r['award_place']} ≠ {p['award']}")
        exp_ex = None if p['excl'] == 'admin' else p['excl']
        if r['excluded_reason'] != exp_ex:
            bad['вне списка'].append(f"{p['name']}: {r['excluded_reason']} ≠ {p['excl']}")
        if bool(r['game_counted']) != p['counted']:
            bad['зачёт Игры'].append(f"{p['name']}: {r['game_counted']} ≠ {p['counted']} ({sorted(w.trace.get(next(x['i'] for x in w.part if x.get('ep_id') == p['ep']), []))})")
        if bool(r['diploma_eligible']) != p['diploma']:
            bad['диплом'].append(f"{p['name']}: {r['diploma_eligible']} ≠ {p['diploma']}")
        if pts.get(uid, 0) != p['pts']:
            bad['очки'].append(f"{p['name']}: {pts.get(uid, 0)} ≠ {p['pts']} (award {p['award']}, top10 {p['top10']}, top25 {p['top25']}, counted {p['counted']}, tw {p['tops']})")
        if stats.get(uid, 0) != p['pts']:
            bad['очки в статистике'].append(f"{p['name']}: {stats.get(uid, 0)} ≠ {p['pts']}")
        cs = certs.get(p['ep'], [])
        if p['diploma'] != bool(cs) or len(cs) > 1:
            bad['выдача диплома'].append(f"{p['name']}: дипломов {len(cs)}, ожидалось {int(p['diploma'])}")
    # номера дипломов: в лиге по месту, потом по алфавиту
    for lg, letter in (('gold', 'G'), ('silver', 'S'), ('bronze', 'B')):
        mem = [p for p in people if p['diploma'] and p['league'] == lg]
        mem.sort(key=lambda p: (p['lrank'] if p['lrank'] is not None else 10 ** 6, (p['name'] or '').lower(), p['ep']))
        for n, p in enumerate(mem, 1):
            want = f'FPL-S{w.season["season_no"]}-{getattr(w, "game_no", 2):02d}-{letter}-{n:04d}'
            cs = certs.get(p['ep'], [])
            if cs and cs[0]['certificate_number'] != want:
                bad['номер диплома'].append(f"{p['name']}: {cs[0]['certificate_number']} ≠ {want}")
            if cs:
                snap = cs[0]['issue_snapshot'] or {}
                title = snap.get('title')
                exp = 'Победитель' if p['award'] == 1 else 'Призёр' if p['award'] in (2, 3) else None
                if p['award'] and exp not in str(title):
                    bad['текст диплома'].append(f"{p['name']}: {title} (место {p['award']})")
    for k2, items in bad.items():
        P.add('critical' if k2 in ('итог', 'место в лиге', 'призовое место', 'очки', 'номер диплома', 'выдача диплома') else 'major',
              area, f'{k2}: {len(items)} расхождений, например: ' + '; '.join(items[:4]))
    w.game_people = people
    print(f'   oracle {area}: {len(people)} participants, {sum(len(v) for v in bad.values())} mismatches')
    # подстроенные равенства
    for lg, mode, a, b in getattr(w, 'engineered', []):
        ra, rb = er.get(a), er.get(b)
        print(f'   engineered {lg} {mode}: totals {ra and ra["final_score"]} / {rb and rb["final_score"]}, '
              f'ranks {ra and ra["league_rank"]} / {rb and rb["league_rank"]}, award {ra and ra["award_place"]} / {rb and rb["award_place"]}')


# ---------------------------------------------------------------- FPL Rating (Elo), своя реализация по Правилам 1.6–1.7

STEPS = {0: (400, 180), 1: (300, 140), 2: (200, 100), 3: (75, 50)}   # K и предел по пройденным калибровочным турам


def check_rating(w, rnd):
    """Снимок на старте судейства = рейтинг после прошлых туров (новичок 500, калибровка 0); изменение = K·Σ(S−E)/n
    с пределом; S — голоса (с переголосованием) или «виртуальные исходы» по оценке в туре по критериям; меняется
    только у тех, кто в конкурсе на публикации и чья работа оценена; пул меньше 3 — без изменений."""
    P = w.p
    area = f'рейтинг, тур {rnd["no"]}'
    state = w.__dict__.setdefault('rating_state', {})          # user → (рейтинг, калибровка)
    snaps = {str(s['event_participant_id']): s for s in w.q('SELECT * FROM round_rating_snapshots WHERE round_id=%s', (rnd['id'],))}
    tx = {str(t['user_id']): t for t in w.q('SELECT * FROM rating_transactions WHERE round_id=%s', (rnd['id'],))}
    bad = defaultdict(list)
    users = {}
    for ep, s in snaps.items():
        uid = str(s['user_id'])
        users[ep] = uid
        want = state.get(uid, (500.0, 0))
        if abs(float(s['rating_snapshot']) - want[0]) > 1e-3 or s['calibration_rounds_completed_before'] != want[1]:
            bad['снимок'].append(f"{float(s['rating_snapshot']):.4f}/{s['calibration_rounds_completed_before']} ≠ {want[0]:.4f}/{want[1]}")
    expect = {}
    for st in w.q('SELECT * FROM evaluation_streams WHERE round_id=%s AND active', (rnd['id'],)):
        targets, res = stream_data(w, st['id'])
        rating = {t: float(snaps[str(r['ep'])]['rating_snapshot']) for t, r in targets.items() if str(r['ep']) in snaps}
        outs = defaultdict(list)
        if st['judging_method'] == 'pairwise':
            for c in w.q("SELECT * FROM pairwise_comparisons WHERE evaluation_stream_id=%s AND status='voted'", (st['id'],)):
                a, b, win = str(c['target_a_id']), str(c['target_b_id']), str(c['winner_target_id'])
                if a in rating and b in rating:
                    if c['counts_for'] in ('both', 'target_a'):
                        outs[a].append((rating[b], 1.0 if win == a else 0.0))
                    if c['counts_for'] in ('both', 'target_b'):
                        outs[b].append((rating[a], 1.0 if win == b else 0.0))
            judged = {t for t in targets if outs.get(t)}
        else:
            crit = {str(c['id']): float(c['weight']) for c in w.q('SELECT * FROM evaluation_criteria WHERE evaluation_stream_id=%s', (st['id'],))}
            by = defaultdict(lambda: defaultdict(dict))
            for s in w.q("SELECT * FROM criterion_scores WHERE evaluation_stream_id=%s AND status='valid'", (st['id'],)):
                by[str(s['evaluation_target_id'])][s['judge_slot_id']][str(s['criterion_id'])] = float(s['score'])
            tw = sum(crit.values())
            val = {}
            for t in targets:
                pj = [sum(sc[c] * x for c, x in crit.items()) / tw for sc in by[t].values() if set(sc) >= set(crit)]
                if pj and t in rating:
                    val[t] = sum(pj) / len(pj)
            for t, v in val.items():
                for o, u in val.items():
                    if o != t:
                        outs[t].append((rating[o], 1.0 if v > u + 1e-9 else 0.0 if v < u - 1e-9 else 0.5))
            judged = set(val)
        pool = sum(1 for t, r in res.items() if r['display_score'] is not None)
        for t, r in res.items():
            ep = str(targets[t]['ep'])
            uid = users.get(ep)
            in_comp = r['qualified'] is not None
            if pool >= 3 and in_comp and t in judged and uid:
                cal = state.get(uid, (500.0, 0))[1]
                k, cap = STEPS[min(3, cal)]
                me = rating[t]
                raw = k * sum(sres - 1 / (1 + 10 ** ((opp - me) / 400)) for opp, sres in outs[t]) / len(outs[t])
                d = max(-cap, min(cap, raw))
                before = state.get(uid, (500.0, 0))[0]
                expect[uid] = (before, raw, d, before + d, k, cap, min(3, cal + 1))
    for uid, (before, raw, d, after, k, cap, cal) in expect.items():
        t = tx.get(uid)
        if t is None:
            bad['нет изменения'].append(uid[:8])
            continue
        got = (float(t['rating_before']), float(t['delta_before_cap']), float(t['delta_after_cap']), float(t['rating_after']),
               float(t['k_used']), float(t['cap_used']))
        want = (before, raw, d, after, k, cap)
        if any(abs(x - y) > 2e-4 for x, y in zip(got, want)):
            bad['изменение'].append(f'{got} ≠ {tuple(round(x, 4) for x in want)}')
        state[uid] = (float(t['rating_after']), cal)
    extra = set(tx) - set(expect)
    if extra:
        bad['лишнее изменение (вне конкурса / без оценки)'].append(f'{len(extra)} чел.')
    for k2, items in bad.items():
        P.add('critical', area, f'{k2}: {len(items)}, например: ' + '; '.join(items[:3]))
    stats = {str(s['user_id']): float(s['current_rating']) for s in w.q('SELECT * FROM participant_stats WHERE current_rating IS NOT NULL')}
    off = [u for u, (r, _) in state.items() if abs(stats.get(u, -1) - r) > 1e-3]
    P.check(not off, 'critical', area, f'рейтинг в профиле ≠ последнему изменению: {len(off)}')
    print(f'   oracle {area}: изменений {len(tx)}, ожидалось {len(expect)}, расхождений {sum(len(v) for v in bad.values())}')

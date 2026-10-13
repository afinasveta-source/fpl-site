"""Итоги Игры без базы: итог 40/60, места в лиге, общий список, равенства, очки, номера дипломов."""
from kabinet.results import compute as C


def person(i, league, scores, **kw):
    return C.Person(id=f'p{i}', user_id=f'u{i}', name=kw.pop('name', f'Имя {i}'), league=league, scores=scores, **kw)


def cfg(**kw):
    return C.config_defaults(kw, [1, 2, 3, 4, 5])


def test_defaults():
    c = cfg()
    assert c['final_round'] == 5 and c['path_rounds'] == [1, 2, 3, 4] and c['path_weight'] == 40
    assert c['points']['places']['gold'] == [20, 15, 12] and c['points']['top_work'] == 1
    c = cfg(path_rounds=[2, 3, 4, 5], points={'top10': 9})            # финал в путь не входит
    assert c['path_rounds'] == [2, 3, 4] and c['points']['top10'] == 9 and c['points']['top25'] == 5
    assert C.config_defaults({}, [1])['path_weight'] == 0                # один тур — он и финал


def test_total_places_and_standing():
    people = [
        person(1, 'gold', {1: 80, 2: 70, 3: 60, 4: 50, 5: 90}),   # путь 65 → 0.4·65 + 0.6·90 = 80
        person(2, 'gold', {1: 90, 2: 90, 3: 90, 4: 90, 5: 70}),   # 0.4·90 + 0.6·70 = 78
        person(3, 'silver', {1: 50, 2: 50, 3: 50, 4: 50, 5: 100}),  # 80
        person(4, 'gold', {1: 99, 2: 99, 3: 99, 4: 95}),           # выбыла после 4 тура
        person(5, 'gold', {1: 99, 2: 30}),                          # выбыла после 2 тура
        person(6, 'gold', {1: 99, 2: 99}, excluded='late'),         # опоздала — вне общего списка
    ]
    out = C.compute(people, cfg())
    by = {p.id: p for p in out}
    assert by['p1'].total == 80 and by['p2'].total == 78 and by['p3'].total == 80
    # общий список: финалисты по итогу (при равном итоге — выше финал), потом выбывшие позже
    assert [p.id for p in out[:5]] == ['p3', 'p1', 'p2', 'p4', 'p5'] and by['p6'].overall_rank is None
    assert [by[x].overall_rank for x in ('p3', 'p1', 'p2', 'p4', 'p5')] == [1, 2, 3, 4, 5]
    # места в лиге и призовые 1–3 — только финалистам
    assert (by['p1'].league_rank, by['p1'].award_place) == (1, 1) and by['p2'].award_place == 2
    assert by['p4'].league_rank == 3 and by['p4'].award_place is None and by['p3'].award_place == 1


def test_tie_needs_decision():
    people = [person(1, 'gold', {1: 60, 2: 60}), person(2, 'gold', {1: 60, 2: 60}), person(3, 'gold', {1: 10, 2: 20})]
    c = C.config_defaults({}, [1, 2])
    out = C.compute(people, c)
    by = {p.id: p for p in out}
    assert by['p1'].league_rank == by['p2'].league_rank == 1 and set(by['p1'].tie) == {'p1', 'p2'}
    assert by['p1'].award_place is None and by['p3'].award_place == 3
    c['tie_orders'] = [{'league': 'gold', 'order': ['p2', 'p1'], 'reason': 'жюри'}]
    for p in people:
        p.tie, p.award_place, p.league_rank = [], None, None
    out = C.compute(people, c)
    by = {p.id: p for p in out}
    assert (by['p2'].award_place, by['p1'].award_place) == (1, 2) and not by['p1'].tie
    assert by['p1'].overall_rank == by['p2'].overall_rank == 1          # общий список равных не разводит


def test_points_best_only_plus_top_work():
    grid = C.DEFAULT_POINTS
    p = person(1, 'silver', {}, counted=True, top_works=['r1', 'r2'], top10=True)
    p.award_place = 1
    assert C.points_for(p, grid) == {'best': 'place_1', 'result': 12, 'top_work': 2, 'total': 14}
    q = person(2, 'silver', {}, counted=True, top10=True, top25=True)
    assert C.points_for(q, grid)['best'] == 'top10' and C.points_for(q, grid)['total'] == 8
    r = person(3, 'gold', {}, counted=True)
    assert C.points_for(r, grid)['total'] == 3
    t = person(5, 'gold', {}, counted=True, top25=True)
    assert C.points_for(t, grid)['best'] == 'top25'
    d = person(4, 'gold', {}, excluded='disqualified', counted=True, top_works=['x'], top10=True)
    assert C.points_for(d, grid)['total'] == 0


def test_top10_top25_per_league_capped_20_percent():
    """TOP-10 / TOP-25 — в своей лиге: места до 10 (25), но не больше 20% лиги; лига от 30 (100) человек (13.10)."""
    gold = [person(i, 'gold', {1: 100 - i}) for i in range(40)]          # 40 в Gold → 20% = 8
    silver = [person(100 + i, 'silver', {1: 100 - i}) for i in range(20)]  # 20 в Silver — меньше 30, TOP-10 нет
    out = C.compute(gold + silver, C.config_defaults({}, [1]))
    g10 = [p for p in out if p.league == 'gold' and p.top10]
    assert len(g10) == 8 and max(p.league_rank for p in g10) == 8
    assert not any(p.top10 for p in out if p.league == 'silver') and not any(p.top25 for p in out)
    big = [person(i, 'bronze', {1: 200 - i}) for i in range(130)]         # 130 в Bronze → TOP-10 = 10, TOP-25 = 25 (20% = 26)
    out = C.compute(big, C.config_defaults({}, [1]))
    assert sum(p.top10 for p in out) == 10 and sum(p.top25 for p in out) == 25
    small = C.compute([person(i, 'gold', {1: 50 - i}) for i in range(10)], C.config_defaults({'points': {'top10_min': 1}}, [1]))
    assert sum(p.top10 for p in small) == 2                               # 20% от 10


def test_no_final_round():
    c = C.config_defaults({'final_round': None}, [1, 2, 3])
    assert c['final_round'] is None and c['path_rounds'] == [1, 2, 3] and c['path_weight'] == 100
    people = [person(1, 'gold', {1: 50, 2: 70, 3: 90}), person(2, 'gold', {1: 90, 2: 90, 3: 30})]
    out = C.compute(people, c)
    assert out[0].total == out[1].total == 70 and out[0].overall_rank == out[1].overall_rank == 1   # равны — одно место


def test_diploma_numbers():
    people = [person(1, 'gold', {}, diploma=True, name='Яна'), person(2, 'gold', {}, diploma=True, name='Анна'),
              person(3, 'silver', {}, diploma=True), person(4, 'gold', {}, diploma=False)]
    people[0].league_rank = 1
    nums = C.diploma_numbers(people, 1, 2)
    assert nums == {'p1': 'FPL-S1-02-G-0001', 'p2': 'FPL-S1-02-G-0002', 'p3': 'FPL-S1-02-S-0001'}
    assert C.diploma_numbers(people[:1], 1, 2, taken={'gold': 7}) == {'p1': 'FPL-S1-02-G-0008'}


def test_round1_eliminated_out_of_standing():
    """Выбывшие в 1 туре — вне мест и TOP-10/25 (решение 13.10)."""
    people = [person(i, 'gold', {1: 90 - i, 2: 80 - i}) for i in range(5)] + [person(9, 'gold', {1: 10})]
    out = {p.id: p for p in C.compute(people, C.config_defaults({'points': {'top10_min': 1}}, [1, 2]))}
    assert out['p9'].excluded == 'not_qualified_round1' and out['p9'].overall_rank is None and out['p9'].league_rank is None
    assert not out['p9'].top10 and out['p0'].league_rank == 1
    one = {p.id: p for p in C.compute([person(1, 'gold', {1: 50}), person(2, 'gold', {1: 40})], C.config_defaults({}, [1]))}
    assert one['p2'].excluded is None and one['p2'].league_rank == 2           # Игра из одного тура — это и есть финал


def test_total_rounds_half_up_exactly():
    """37,675 → 37,68: путь 61,75 × 10% + финал 35 × 90% (во float было 37,67; Codex, 13.10)."""
    c = C.config_defaults({'path_weight': 10}, [1, 2, 3, 4, 5])
    out = C.compute([person(1, 'gold', {1: 71, 2: 53, 3: 36, 4: 87, 5: 35})], c)
    assert out[0].total == 37.68
    assert C.half_up(2.675, 2) == 2.68 and C.half_up(1.005, 2) == 1.01 and C.half_up(-0.5) == 0.0

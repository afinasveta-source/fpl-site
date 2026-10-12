"""Расчёты судейства без базы: жеребьёвка, балл, места, TOP WORK, граница прохода, переголосование, рейтинг."""
from collections import Counter

from kabinet.judging import compute as C


def test_draw_pairs_balanced_and_unique():
    targets = list(range(20))
    out = C.draw_pairs(targets, ['j1', 'j2', 'j3'], 2, seed=1)
    seen = set()
    for judge, pairs in out.items():
        per = Counter(x for p in pairs for x in p)
        assert set(per.values()) == {2} and len(pairs) == 20          # каждая работа — 2 раза у судьи
        keys = {frozenset(p) for p in pairs}
        assert len(keys) == len(pairs)                                  # у одного судьи пары не повторяются
        assert not keys & seen                                          # и у разных судей — тоже
        seen |= keys
    out4 = C.draw_pairs(targets, ['j1', 'j2', 'j3'], 4, seed=2)
    assert all(set(Counter(x for p in v for x in p).values()) == {4} for v in out4.values())


def test_draw_pairs_small_pool():
    out = C.draw_pairs([1, 2, 3], ['a', 'b', 'c'], 2, seed=3)
    for pairs in out.values():
        assert len({frozenset(p) for p in pairs}) == len(pairs) == 3
    assert C.draw_pairs([1, 2], ['a'], 2)['a'] in ([(1, 2)], [(2, 1)])
    assert C.draw_pairs([1], ['a'], 2) == {'a': []}


def test_scores():
    # шкала 1–100 (решение 12.10): 1 + 99 × доля побед
    assert C.win_share_score(3, 6) == 51 and C.win_share_score(0, 6) == 1 and C.win_share_score(6, 6) == 100
    assert C.win_share_score(0, 0) is None
    v = C.criteria_value({'j1': {'idea': 100, 'tech': 40}, 'j2': {'idea': 60, 'tech': 60}, 'j3': {'idea': 90}}, {'idea': 2, 'tech': 1})
    assert abs(v - ((240 / 3 + 180 / 3) / 2)) < 1e-9     # неполная оценка судьи j3 не идёт в счёт
    assert C.criteria_score(70) == 70 and C.criteria_score(86.5) == 87 and C.criteria_score(1) == 1 and C.criteria_score(None) is None


def rows(keys):
    return [C.Row(t, k, None if k is None else C.win_share_score(k * 100, 100)) for t, k in keys]


def test_rank_ties_and_top_work():
    order = C.rank_rows(rows([('a', .9), ('b', .7), ('c', .7), ('d', .5), ('e', .3), ('f', None)]))
    assert [(r.target, r.rank, r.tie_group_size) for r in order[:4]] == [('a', 1, 1), ('b', 2, 2), ('c', 2, 2), ('d', 4, 1)]
    assert order[1].average_place == 2.5 and order[-1].target == 'f' and order[-1].rank is None
    C.apply_tie_breaks(order, [])
    assert C.top_work(order) == 1 and [r.target for r in order if r.top_work] == ['a']   # 20% от 5 = 1
    order = C.rank_rows(rows([(i, k) for i, k in enumerate([.9, .8, .8, .6, .5, .4, .3, .2, .1, .05])]))
    C.apply_tie_breaks(order, [])
    assert C.top_work(order) == 3                                                          # 2 + равная на границе
    small = C.rank_rows(rows([('a', .9), ('b', .5), ('c', .1)]))
    assert C.top_work(small) == 0


def test_boundary_tie_and_tie_break():
    order = C.apply_tie_breaks(C.rank_rows(rows([('a', .9), ('b', .6), ('c', .6), ('d', .2)])), [])
    b = C.boundary(order, 2, [])
    assert b['status'] == 'tie' and set(b['tied']) == {'b', 'c'}
    # переголосование: c сильнее b — они меняются местами, проход решён
    groups = [({'b', 'c'}, {'c': 3, 'b': 0})]
    order = C.apply_tie_breaks(C.rank_rows(rows([('a', .9), ('b', .6), ('c', .6), ('d', .2)])), groups)
    assert [r.target for r in order] == ['a', 'c', 'b', 'd']
    b = C.boundary(order, 2, groups)
    assert b['status'] == 'ok' and [r.target for r in order if r.advanced] == ['a', 'c']
    # решение организатора тоже снимает равенство
    order = C.apply_tie_breaks(C.rank_rows(rows([('a', .9), ('b', .6), ('c', .6), ('d', .2)])), [])
    b = C.boundary(order, 2, [], admin={'b': False, 'c': True})
    assert b['status'] == 'ok' and {r.target for r in order if r.advanced} == {'a', 'c'}
    # пустой проход — проходят все
    assert C.boundary(order, None, [])['status'] == 'ok' and all(r.advanced for r in order)


def test_tie_break_keeps_positions():
    """Переголосование не двигает работы за пределы своих позиций."""
    order = C.rank_rows(rows([('a', .9), ('b', .7), ('c', .7), ('d', .7), ('e', .1)]))
    order = C.apply_tie_breaks(order, [({'b', 'd'}, {'d': 2, 'b': 1})])
    assert [r.target for r in order] == ['a', 'd', 'c', 'b', 'e'] and [r.position for r in order] == [1, 2, 3, 4, 5]


def test_elo():
    raw, d, k, cap = C.elo_delta(500, [(500, 1), (500, 0)], 0)
    assert raw == 0 and d == 0 and k == 400 and cap == 180
    raw, d, *_ = C.elo_delta(500, [(500, 1)] * 4, 0)
    assert raw == 200 and d == 180                       # предел калибровки 0
    raw, d, k, cap = C.elo_delta(600, [(600, 1)], 3)
    assert (k, cap) == (75, 50) and d == 37.5
    assert C.elo_delta(500, [], 1)[1] == 0
    v = C.virtual_outcomes({'a': 9, 'b': 7, 'c': 7}, {'a': 500, 'b': 520, 'c': 480})
    assert sorted(v['a']) == [(480, 1.0), (520, 1.0)] and (480, 0.5) in v['b'] and (500, 0.0) in v['c']


def test_half_up_and_shared_places():
    assert C.win_share_score(1, 2) == 51 and C.win_share_score(1, 198) == 2      # 50,5 → 51; 1,5 → 2 (половина вверх)
    order = C.apply_tie_breaks(C.rank_rows(rows([('a', .5), ('b', .5), ('c', .5), ('d', .1)])), [])
    assert [r.place for r in order] == [1, 1, 1, 4]
    order = C.apply_tie_breaks(C.rank_rows(rows([('a', .5), ('b', .5), ('c', .5), ('d', .1)])), [({'a', 'b', 'c'}, {'c': 2, 'a': 1, 'b': 1})])
    assert [(r.target, r.place) for r in order][:1] == [('c', 1)] and sorted(r.place for r in order[1:3]) == [2, 2]


def test_boundary_single_and_unjudged():
    one = C.apply_tie_breaks(C.rank_rows(rows([('a', None)])), [])
    assert C.boundary(one, 1, [])['status'] == 'ok' and one[0].advanced is True
    two = C.apply_tie_breaks(C.rank_rows(rows([('a', .9), ('b', None)])), [])
    b = C.boundary(two, 1, [])
    assert b['status'] == 'unjudged' and b['unjudged'] == ['b']
    b = C.boundary(two, 1, [], admin={'b': False})
    assert b['status'] == 'ok' and two[1].advanced is False


def test_bradley_terry_strength_of_schedule():
    """Брэдли–Терри: победа над сильной работой весит больше, чем над слабой; итог не зависит от порядка голосов."""
    import random as rnd
    games = []
    for f in ('f1', 'f2', 'f3', 'f4'):
        games += [('S', f, 'S', True, True), (f, 'W', f, True, True)]       # S сильная, W слабая
    games += [('X', 'S', 'X', True, True), ('X', 'S', 'S', True, True)]     # X: 1 из 2 против сильной
    games += [('Y', 'W', 'Y', True, True), ('Y', 'W', 'W', True, True)]     # Y: 1 из 2 против слабой
    sh = C.bt_shares(C.bradley_terry(games))
    assert sh['X'] > sh['Y'] and sh['S'] > sh['X'] and sh['Y'] > sh['W']
    shuffled = games[:]
    rnd.Random(5).shuffle(shuffled)
    sh2 = C.bt_shares(C.bradley_terry(shuffled))
    assert all(abs(sh[t] - sh2[t]) < 1e-9 for t in sh)


def test_bradley_terry_bounds_and_equal():
    # круговой турнир «каждый с каждым по разу в обе стороны» — все равны: балл 51 у всех (50,5 → 51)
    names = ['a', 'b', 'c', 'd']
    games = [(x, y, w, True, True) for i, x in enumerate(names) for y in names[i + 1:] for w in (x, y)]
    sh = C.bt_shares(C.bradley_terry(games))
    assert {C.share_score(v) for v in sh.values()} == {51}
    # 6 из 6 и 0 из 6 — конечные баллы (поправка), не 100 и не 1
    games = [('top', o, 'top', True, True) for o in 'pqrstu'] + [('low', o, o, True, True) for o in 'pqrstu']
    sh = C.bt_shares(C.bradley_terry(games))
    assert 51 < C.share_score(sh['top']) < 100 and 1 < C.share_score(sh['low']) < 51
    assert C.bradley_terry([]) == {} and C.share_score(None) is None


def test_bradley_terry_one_sided():
    """Сравнение «в счёт только одной стороне» не меняет силу другой стороны."""
    base = [('a', 'b', 'a', True, True), ('b', 'c', 'b', True, True), ('c', 'a', 'c', True, True)]
    one = base + [('d', 'a', 'd', True, False)]           # досудейство d: победа над a в счёт только d
    s0, s1 = C.bradley_terry(base), C.bradley_terry(one)
    assert abs(s0['a'] - s1['a']) < 1e-9 and 'd' in s1 and s1['d'] > s1['a']

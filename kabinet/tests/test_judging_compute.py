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
    assert C.win_share_score(3, 6) == 70 and C.win_share_score(0, 6) == 40 and C.win_share_score(6, 6) == 100
    assert C.win_share_score(0, 0) is None
    v = C.criteria_value({'j1': {'idea': 10, 'tech': 4}, 'j2': {'idea': 6, 'tech': 6}, 'j3': {'idea': 9}}, {'idea': 2, 'tech': 1})
    assert abs(v - ((24 / 3 + 18 / 3) / 2)) < 1e-9       # неполная оценка судьи j3 не идёт в счёт
    assert C.criteria_score(1) == 40 and C.criteria_score(10) == 100 and C.criteria_score(5.5) == 70


def rows(keys):
    return [C.Row(t, k, None if k is None else round(40 + 60 * k)) for t, k in keys]


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
    assert C.win_share_score(3, 8) == 63 and C.win_share_score(7, 8) == 93     # как ROUND в базе бота
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

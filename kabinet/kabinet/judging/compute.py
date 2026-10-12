"""Судейство: чистые расчёты без базы — жеребьёвка пар, балл 1–100, места, TOP WORK, граница прохода, рейтинг.

Решения Светланы (документы проекта «Чат бот»):
- балл тура — по шкале 1–100 (решение 12.10; шкала 40–100 была только в первом туре Игры 01):
  сравнение пар — 1 + 99 × победы / сравнения, в счёт идут и сравнения переголосования (win_share_100_v1);
  критерии — судьи ставят 1–100 по каждому критерию, среднее с весами критериев, затем среднее по судьям
  (criteria_mean_100_v1);
- место — по доле побед (или оценке); одинаковые — одно место; хранится и среднее место группы;
- TOP WORK: min(10, floor(20% пула)), равные на границе — все, при пуле < 5 — нет (FPL_TOPWORK_V1);
- проход: число по лиге задаёт организатор; равные на границе — переголосование или решение организатора;
- переголосование меняет порядок только внутри своей группы: работы занимают те же позиции, порядок —
  по победам в переголосовании, при равенстве — по баллу тура (решение 12.10);
- FPL Rating: Elo по голосам, рейтинги из снимка на начало судейства; K и предел по калибровке (24.09);
  тур по критериям — «виртуальные исходы» внутри пула по оценке работы (решение 11.10, criteria_virtual_elo).
"""
import math
import random
from dataclasses import dataclass, field

SCALE_MIN, SCALE_MAX = 1, 100
CRITERIA_MIN, CRITERIA_MAX = 1, 100   # оценка судьи по критерию
TOPWORK_RULE = 'FPL_TOPWORK_V1'
ELO_FORMULA = 'FPL_ELO_V1'
NEWCOMER_RATING = 500
# (K, предел изменения) по числу пройденных калибровочных туров до этого тура
ELO_STEPS = {0: (400, 180), 1: (300, 140), 2: (200, 100), 3: (75, 50)}
CLOSE_MARGIN = 2   # «близко к границе» — разница меньше 2 баллов


# ---------- жеребьёвка ----------

def draw_pairs(targets, judges, per_target, seed=None):
    """Пары для каждого судьи: каждая работа у судьи встречается per_target раз (чётное число), соперники разные.

    Один случайный круговой порядок работ; судья j берёт смещения своего диапазона — так пары у разных судей не
    повторяются. Если работ мало и диапазоны не помещаются, у судьи свой случайный порядок (повтор пары у разных
    судей допустим, у одного — нет). Возвращает {судья: [(a, b), ...]} в случайном порядке показа.
    """
    targets = list(targets)
    n = len(targets)
    rng = random.Random(seed)
    if n < 2 or not judges:
        return {j: [] for j in judges}
    half = max(1, per_target // 2)
    base = targets[:]
    rng.shuffle(base)
    out = {}
    for j, judge in enumerate(judges):
        offsets = list(range(j * half + 1, j * half + half + 1))
        order = base
        if max(offsets) * 2 >= n:          # диапазон судьи не помещается в круг — свой порядок и ближние смещения
            order = targets[:]
            rng.shuffle(order)
            offsets = [d for d in range(1, half + 1) if d * 2 <= n] or [1]
        seen, pairs = set(), []
        for d in offsets:
            for i in range(n):
                a, b = order[i], order[(i + d) % n]
                key = frozenset((a, b))
                if a == b or key in seen:
                    continue
                seen.add(key)
                pairs.append((a, b) if rng.random() < 0.5 else (b, a))
        rng.shuffle(pairs)
        out[judge] = pairs
    return out


def tie_break_pairs(targets, seed=None):
    """Переголосование: все пары среди выбранных работ (3 работы — 3 пары), стороны и порядок случайные."""
    rng = random.Random(seed)
    t = list(targets)
    pairs = [(t[i], t[k]) if rng.random() < 0.5 else (t[k], t[i]) for i in range(len(t)) for k in range(i + 1, len(t))]
    rng.shuffle(pairs)
    return pairs


def half_up(x):
    """Округление «половина — вверх», как ROUND в базе бота Игры 01 (у Python round 62,5 → 62)."""
    return int(math.floor(x + 0.5))


# ---------- балл ----------

def win_share_score(wins, total):
    if not total:
        return None
    return half_up(SCALE_MIN + (SCALE_MAX - SCALE_MIN) * wins / total)


def criteria_value(judge_scores, weights):
    """judge_scores: {судья: {критерий: оценка}} — только полные оценки судьи. Среднее с весами, потом по судьям."""
    per_judge = []
    total_w = sum(weights.values())
    for scores in judge_scores.values():
        if set(scores) >= set(weights):
            per_judge.append(sum(scores[c] * w for c, w in weights.items()) / total_w)
    if not per_judge:
        return None
    return sum(per_judge) / len(per_judge)


def criteria_score(value):
    """Оценки судей уже по шкале 1–100 — балл тура = среднее, округлённое половина вверх."""
    if value is None:
        return None
    return half_up(value)


# ---------- места, TOP WORK, проход ----------

@dataclass
class Row:
    target: object
    key: float | None          # чем больше, тем выше (доля побед или оценка)
    score: int | None          # балл 1–100 для показа
    rank: int | None = None
    average_place: float | None = None
    tie_group_size: int | None = None
    position: int | None = None   # позиция в порядке после переголосований (1..n — для показа организатору)
    place: int | None = None      # место: равные делят место; переголосование разводит своих
    top_work: bool = False
    advanced: bool | None = None
    extra: dict = field(default_factory=dict)


def rank_rows(rows):
    """Места по ключу: одинаковый ключ — одно место (1, 2, 2, 4); среднее место группы; без оценки — в конце без места."""
    scored = sorted([r for r in rows if r.key is not None], key=lambda r: -r.key)
    i = 0
    while i < len(scored):
        k = i
        while k + 1 < len(scored) and math.isclose(scored[k + 1].key, scored[i].key, abs_tol=1e-9):
            k += 1
        size = k - i + 1
        for r in scored[i:k + 1]:
            r.rank, r.tie_group_size, r.average_place = i + 1, size, (i + 1 + k + 1) / 2
        i = k + 1
    return scored + [r for r in rows if r.key is None]


def apply_tie_breaks(ordered, groups):
    """ordered — строки по месту; groups — [(члены, {член: победы в переголосовании})] в порядке проведения.
    Члены группы занимают те же позиции, что занимали, порядок — по победам, при равенстве — по ключу.
    Возвращает новый порядок; у решённых групп отметка extra['tie_break'] и номер позиции."""
    order = list(ordered)
    for members, wins in groups:
        idx = sorted(i for i, r in enumerate(order) if r.target in members and r.key is not None)
        if len(idx) < 2:
            continue
        chosen = sorted((order[i] for i in idx), key=lambda r: (-wins.get(r.target, 0), -(r.key or 0)))
        for i, r in zip(idx, chosen):
            order[i] = r
            r.extra['tie_break_wins'] = wins.get(r.target, 0)
    for pos, r in enumerate(order, 1):
        r.position = pos if r.key is not None else None
    # место: равные (не разведённые переголосованием) делят первое из своих мест
    scored = [r for r in order if r.key is not None]
    for i, r in enumerate(scored):
        r.place = r.position
        if i and tie_unresolved(order, scored[i - 1], r, groups):
            r.place = scored[i - 1].place
    return order


def tie_unresolved(order, a, b, groups):
    """Равны ли строки a и b по ключу и не разведены переголосованием, где обе участвовали."""
    if a.key is None or b.key is None or not math.isclose(a.key, b.key, abs_tol=1e-9):
        return False
    for members, wins in groups:
        if a.target in members and b.target in members and wins.get(a.target, 0) != wins.get(b.target, 0):
            return False
    return True


def top_work(order, n=None):
    """Отметить TOP WORK по правилу. Возвращает число отмеченных."""
    n = n if n is not None else sum(1 for r in order if r.key is not None)
    if n < 5:
        return 0
    quota = min(10, math.floor(n * 0.2))
    if quota <= 0:
        return 0
    scored = [r for r in order if r.key is not None]
    cut = scored[quota - 1].key
    count = 0
    for r in scored:
        if r.key >= cut - 1e-9:
            r.top_work = True
            count += 1
    return count


def boundary(order, quota, groups, admin=None):
    """Проход: первые quota по позиции (order — только работы, которые борются за проход).
    Если на границе равные (не разведённые переголосованием) — нужна развязка. Работа без оценки — только решением
    организатора (кроме единственной работы пула — она проходит). admin — {цель: прошла} решения организатора.
    Возвращает {'status': ok/tie, 'tied': [цели на границе], 'unjudged': [без оценки], 'close': [...], 'cut_score'}."""
    admin = admin or {}
    scored = [r for r in order if r.key is not None]
    unjudged = [r for r in order if r.key is None]
    for r in order:
        r.advanced = None
    tied, close, cut = [], [], None
    if quota is None or quota >= len(scored):
        for r in scored:
            r.advanced = True
    else:
        for i, r in enumerate(scored):
            r.advanced = i < quota
        last_in, first_out = scored[quota - 1], scored[quota]
        if tie_unresolved(order, last_in, first_out, groups):
            tied = [r.target for r in scored if tie_unresolved(order, r, last_in, groups) or r is last_in]
        cut = last_in.score
        close = [r.target for r in scored if cut is not None and r.score is not None and abs(r.score - cut) < CLOSE_MARGIN]
    if len(order) == 1 and unjudged:
        unjudged[0].advanced = True          # единственная работа пула — сравнивать не с кем
        unjudged = []
    for r in order:
        if r.target in admin:
            r.advanced = admin[r.target]
    tied = [t for t in tied if t not in admin] if not all(t in admin for t in tied) else []
    pending = [r.target for r in unjudged if r.target not in admin]
    return {'status': 'tie' if tied else 'unjudged' if pending else 'ok', 'tied': tied, 'unjudged': pending,
            'close': close, 'quota': quota, 'cut_score': cut}


# ---------- рейтинг ----------

def elo_params(calibration_before):
    return ELO_STEPS[min(3, max(0, calibration_before))]


def elo_delta(rating, outcomes, calibration_before):
    """outcomes — [(рейтинг соперника, результат 1 / 0.5 / 0)]. Δ = K × Σ(S − E) / n, затем предел."""
    if not outcomes:
        return 0.0, 0.0, None, None
    k, cap = elo_params(calibration_before)
    total = sum(s - 1 / (1 + 10 ** ((opp - rating) / 400)) for opp, s in outcomes)
    raw = k * total / len(outcomes)
    return raw, max(-cap, min(cap, raw)), k, cap


def virtual_outcomes(values, snapshot):
    """Тур по критериям: каждая работа «сыграла» со всеми в пуле — выше оценка = победа, равная = ничья.
    values — {цель: оценка}, snapshot — {цель: рейтинг}. Возвращает {цель: [(рейтинг соперника, S)]}."""
    out = {t: [] for t in values}
    items = [(t, v) for t, v in values.items() if v is not None]
    for t, v in items:
        for o, w in items:
            if o == t:
                continue
            out[t].append((snapshot[o], 1.0 if v > w + 1e-9 else 0.0 if v < w - 1e-9 else 0.5))
    return out

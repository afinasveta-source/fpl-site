"""Итоги Игры: чистые расчёты без базы — итоговый балл, места в лиге, общий список (TOP-10/25), очки FPL, дипломы.

Решения Светланы (документы проекта «Чат бот»):
- итог Игры = путь × вес + финал × (100 − вес); путь — средний балл выбранных туров (по умолчанию все туры до финала,
  первый тоже — по баллу Брэдли–Терри), финал — балл последнего тура; по умолчанию 40/60 (11.10, 12.10);
- места 1–3 — в своей лиге, только среди дошедших до финала; при равном итоге — выше балл финала, дальше решает
  организатор (24.09: «тай-брейк объявляется заранее» — в кабинете это решение организатора с причиной);
- общий список Игры (для TOP-10 и TOP-25), правило Игры 01 (03.10): сначала дошедшие до финала — по итогу, потом выбывшие
  после последнего тура, потом раньше — каждый по баллу тура, где выбыл. Опоздавшие, вышедшие и дисквалифицированные
  в список не входят. Без выбывания все доходят до финала — список просто по итогу;
- места и общий список показываются только в итогах Игры (12.10);
- очки FPL: за итог Игры одно, самое высокое достижение (место 1–3 в лиге, TOP-10, TOP-25, завершение = зачёт Игры) +
  TOP WORK за каждую работу (03.10); сетка задаётся в настройках Игры (12.10);
- диплом — все работы сданы до конца Игры; призёрам 1–3 места в лиге — с местом (12.10).
"""
import math
from dataclasses import dataclass, field

FORMULA = 'GAME_PATH_FINAL_V1'
LEAGUE_LETTER = {'gold': 'G', 'silver': 'S', 'bronze': 'B'}
LEAGUE_NAME = {'gold': 'Gold', 'silver': 'Silver', 'bronze': 'Bronze'}

# Сетка по умолчанию: Игра 01 (Лига А = Gold, Лига Б = Silver, решение 03.10). Для Bronze — та же логика «1 место
# нижней лиги = 3 место лиги выше» (12.10: значения можно поменять в настройках Игры до старта).
DEFAULT_POINTS = {
    'places': {'gold': [20, 15, 12], 'silver': [12, 10, 8], 'bronze': [8, 6, 5]},
    'top10': 8, 'top25': 5, 'completion': 3, 'top_work': 1,
    'top25_min': 100,      # TOP-25 — только в больших Играх: в общем списке не меньше 100 человек (решение 13.10)
}
DEFAULT_PATH_WEIGHT = 40


def half_up(x, digits=0):
    q = 10 ** digits
    return math.floor(x * q + 0.5) / q


@dataclass
class Person:
    id: str                       # event_participant_id
    user_id: str
    name: str
    league: str | None
    scores: dict                  # номер тура → балл (туры, где судили в конкурсе); None — без оценки
    excluded: str | None = None   # late / withdrawn / disqualified — вне общего списка
    counted: bool = False         # зачёт Игры (все работы в срок)
    diploma: bool = False         # все работы сданы до конца Игры
    top_works: list = field(default_factory=list)   # id итогов туров с TOP WORK
    # расчёт
    stage: int | None = None
    finalist: bool = False
    path: float | None = None
    final: float | None = None
    total: float | None = None
    league_rank: int | None = None
    award_place: int | None = None
    overall_rank: int | None = None
    tie: list = field(default_factory=list)          # не разведённые равные на местах 1–3 (id)
    points: dict = field(default_factory=dict)


def config_defaults(cfg, round_nos):
    """Настройки итогов Игры с умолчаниями. round_nos — номера туров Игры (не черновики)."""
    cfg = dict(cfg or {})
    rounds = sorted(round_nos)
    final = cfg.get('final_round', rounds[-1] if rounds else None)
    if final is not None and final not in rounds:
        final = rounds[-1] if rounds else None
    path = cfg.get('path_rounds')
    if path is None:
        path = [n for n in rounds if n != final]
    path = [n for n in path if n in rounds and n != final]
    weight = cfg.get('path_weight', DEFAULT_PATH_WEIGHT)
    if final is None or not path:
        weight = 100 if final is None else 0
    points = {**DEFAULT_POINTS, **(cfg.get('points') or {})}
    points['places'] = {**DEFAULT_POINTS['places'], **((cfg.get('points') or {}).get('places') or {})}
    return {'final_round': final, 'path_rounds': path, 'path_weight': weight, 'points': points,
            'tie_orders': cfg.get('tie_orders', [])}


def compute(people, cfg, awards_points=True):
    """Считает итог, места, общий список и очки. people — [Person]; cfg — из config_defaults.
    Возвращает список людей в порядке общего списка (сначала вошедшие, потом остальные)."""
    final, path_rounds, w = cfg['final_round'], cfg['path_rounds'], cfg['path_weight'] / 100
    # последний тур Игры: финал, а без финала — последний тур пути (дошедшие до него ранжируются по итогу)
    last = final if final is not None else (max(path_rounds) if path_rounds else None)
    for p in people:
        judged = [n for n in p.scores]
        p.stage = max(judged) if judged else None
        p.finalist = last is not None and last in p.scores and p.excluded is None
        path = [p.scores[n] for n in path_rounds if p.scores.get(n) is not None]
        p.path = sum(path) / len(path) if path else None
        p.final = p.scores.get(final) if final is not None else None
        if not p.finalist:
            continue
        if final is None:
            p.total = half_up(p.path, 2) if p.path is not None else None
        elif p.final is None:
            p.total = None            # финал без оценки — итога нет, в места и общий список не входит
        elif p.path is None or w == 0:
            p.total = half_up(p.final, 2)
        else:
            p.total = half_up(p.path * w + p.final * (1 - w), 2)
    ranked = [p for p in people if p.excluded is None and p.stage is not None and stage_value(p, final) is not None]
    ranked.sort(key=lambda p: standing_key(p, final))
    # общий список: равные делят место (1, 1, 3)
    prev = None
    for i, p in enumerate(ranked, 1):
        p.overall_rank = prev.overall_rank if prev is not None and standing_key(prev, final) == standing_key(p, final) else i
        prev = p
    # места в лиге — тем же порядком внутри лиги; на местах 1–3 дошедших до финала равенство разводит организатор
    orders = cfg.get('tie_orders') or []
    for league in sorted({p.league for p in ranked if p.league}):
        members = [p for p in ranked if p.league == league]
        members = apply_tie_orders(members, final, orders, league)
        pos, prev = 0, None
        for p in members:
            pos += 1
            same = prev is not None and standing_key(prev, final) == standing_key(p, final) and not decided(prev, p, orders, league)
            p.league_rank = prev.league_rank if same else pos
            prev = p
        finalists = [p for p in members if p.finalist and p.total is not None]
        for p in finalists:
            if p.league_rank <= 3:
                group = [q.id for q in finalists if q.league_rank == p.league_rank]
                if len(group) > 1:
                    p.tie = group
                else:
                    p.award_place = p.league_rank
    if awards_points:
        for p in people:
            p.points = points_for(p, cfg['points'], len(ranked))
    rest = [p for p in people if p not in ranked]
    return ranked + sorted(rest, key=lambda p: p.name.lower())


def stage_value(p, final):
    """Чем выше, тем лучше: дошедшим до финала — итог, выбывшим — балл тура, где выбыли."""
    if p.finalist:
        return p.total
    return p.scores.get(p.stage)


def standing_key(p, final):
    """Ключ общего списка (по возрастанию): дальше прошла → выше; итог / балл тура; при равном итоге — балл финала."""
    tier = 0 if p.finalist else 1
    value = stage_value(p, final)
    return (tier, 0 if p.finalist else -(p.stage or 0), -(value if value is not None else -1), -(p.final if p.finalist and p.final is not None else 0))



def decided(a, b, orders, league):
    for o in orders:
        if o.get('league') == league and a.id in o['order'] and b.id in o['order']:
            return True
    return False


def apply_tie_orders(members, final, orders, league):
    """Решения организатора о порядке равных: переставляет их внутри своих позиций."""
    out = list(members)
    for o in orders:
        if o.get('league') != league:
            continue
        idx = [i for i, p in enumerate(out) if p.id in o['order']]
        chosen = sorted((out[i] for i in idx), key=lambda p: o['order'].index(p.id))
        for i, p in zip(idx, chosen):
            out[i] = p
    return out


def top25_on(grid, standing_size):
    return standing_size >= grid.get('top25_min', DEFAULT_POINTS['top25_min'])


def points_for(p, grid, standing_size=0):
    """Очки FPL: одно самое высокое достижение за итог Игры + TOP WORK за каждую работу.
    standing_size — сколько человек в общем списке Игры (TOP-25 есть только в больших Играх)."""
    if p.excluded == 'disqualified':
        return {'best': None, 'result': 0, 'top_work': 0, 'total': 0}
    options = []
    if p.award_place and p.league in grid['places']:
        options.append(('place_%d' % p.award_place, grid['places'][p.league][p.award_place - 1]))
    if p.overall_rank is not None and p.overall_rank <= 10:
        options.append(('top10', grid['top10']))
    if p.overall_rank is not None and p.overall_rank <= 25 and top25_on(grid, standing_size):
        options.append(('top25', grid['top25']))
    if p.counted:
        options.append(('completion', grid['completion']))
    best = max(options, key=lambda x: x[1]) if options else (None, 0)
    tw = len(p.top_works) * grid['top_work']
    return {'best': best[0], 'result': best[1], 'top_work': tw, 'total': best[1] + tw}


def diploma_title(p):
    if p.award_place == 1:
        return 'Победитель'
    if p.award_place in (2, 3):
        return 'Призёр'
    return None


def diploma_numbers(people, season_no, game_no, taken=None):
    """Номера дипломов: FPL-S1-01-G-0001 — в лиге по месту, потом без места по алфавиту.
    taken — {лига: последний выданный номер} (дипломы, выданные раньше). Возвращает {id: номер}."""
    taken = dict(taken or {})
    out = {}
    for league in ('gold', 'silver', 'bronze'):
        members = [p for p in people if p.diploma and p.league == league]
        members.sort(key=lambda p: (p.league_rank if p.league_rank is not None else 10 ** 6, p.name.lower(), p.id))
        n = taken.get(league, 0)
        for p in members:
            n += 1
            out[p.id] = 'FPL-S%d-%02d-%s-%04d' % (season_no, game_no, LEAGUE_LETTER[league], n)
    return out

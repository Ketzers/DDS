"""
scoring.py — скоринговый движок СППР для оценки инвестиционного проекта
открытия квест-комнаты в Москве.

Принимает на вход «гипотезу проекта» (локация, тип, жанр, цена, бюджет),
возвращает структурированное заключение с баллами по 4 критериям,
итоговым скором, вердиктом и рекомендациями по улучшению.

Критерии скоринга:
    1. Конкурентная плотность зоны     — KDE/DBSCAN на парсинге
    2. Соответствие цены спросу         — опрос + парсинг
    3. Конкурентная среда               — медианная популярность конкурентов
    4. Финансовая жизнеспособность      — юнит-экономика на прогнозной заполняемости

Главные функции:
    evaluate_project(input, df, survey)            -> ProjectScore
    suggest_improvements(input, df, survey, score) -> list[Improvement]
    suggest_combined_strategy(input, df, survey, score) -> list[Strategy]
    detect_genre(row)                              -> str  (жанр квеста по тегам)
    predict_occupancy(lat, lon, type, df)          -> tuple[float, str]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal

import math
import pandas as pd

from sppr.survey_metrics import SurveyMetrics
from sppr.metro_stations import (
    MetroStation, find_station, find_quiet_stations, haversine_km,
    get_rent_zone,
)


# ─────────────────────────────────────────────────────────────────────────────
# КОНСТАНТЫ И НАСТРОЙКИ
# ─────────────────────────────────────────────────────────────────────────────

# Базовые экспертные веса критериев. Используются по умолчанию, если
# данные опроса недоступны. Сумма = 1.0.
# Логика приоритетов: локация ≥ среда ≥ финансы ≥ цена.
DEFAULT_CRITERION_WEIGHTS = {
    'competition':  0.30,
    'comp_env':     0.25,
    'price_fit':    0.20,
    'financial':    0.25,
}

# Доля финансового критерия в итоге. Захардкожена экспертно (это не мнение
# аудитории, а инвестиционная гигиена) — не выводится из опроса.
# Остальные 0.75 распределяются между тремя «потребительскими» критериями
# пропорционально рангам факторов из опроса.
FINANCIAL_WEIGHT_FIXED = 0.25

# Маппинг: критерий движка ↔ фактор из опроса
CRITERION_TO_FACTOR = {
    'competition':  'Локация',
    'comp_env':     'Отзывы знакомых',
    'price_fit':    'Цена',
    # 'financial' не маппится — опрос про финансы не спрашивает
}

COMPETITION_RADIUS_KM = 0.9
NEIGHBOR_RADIUS_KM    = 1.0

VERDICT_GREEN_THRESHOLD  = 7.5
VERDICT_YELLOW_THRESHOLD = 5.0

FINANCIAL_PAYBACK_BLOCKER_MONTHS = 36
FINANCIAL_LOSS_BLOCKER           = True

# Жанры, известные системе. Должны быть согласованы с ключами SurveyMetrics.genre_demand
KNOWN_GENRES = [
    'Хоррор', 'Детектив', 'Логический', 'Приключение',
    'Мистика', 'Фантастика', 'Исторический',
]


def compute_weights(survey: 'SurveyMetrics' = None) -> dict:
    """Считает веса критериев на основе рангов факторов из опроса.

    Логика:
        - Финансовый вес фиксирован (0.25) — это инвестиционная гигиена,
          не мнение аудитории.
        - Оставшиеся 0.75 делятся между competition / comp_env / price_fit
          пропорционально «значимости» фактора, выведенной из ранга:
              importance_i = (max_rank + 1) - rank_i
          Чем меньше ранг (=важнее), тем больше вес.
        - Если данные опроса недоступны — используются значения
          DEFAULT_CRITERION_WEIGHTS.

    Returns:
        Словарь весов с ключами 'competition' | 'comp_env' | 'price_fit' | 'financial'.
        Сумма всех весов = 1.0.
    """
    if survey is None:
        return dict(DEFAULT_CRITERION_WEIGHTS)

    # Извлекаем ранги для трёх потребительских критериев
    ranks = {}
    for criterion, factor in CRITERION_TO_FACTOR.items():
        rank = survey.factor_ranks.get(factor)
        if rank is None or rank <= 0:
            return dict(DEFAULT_CRITERION_WEIGHTS)
        ranks[criterion] = rank

    # Преобразуем ранг в «важность»: чем меньше ранг, тем выше важность.
    # Ранги обычно в диапазоне 1-6, но мы берём (max + 1 - rank), где
    # max — максимальный ранг в нашем множестве (для устойчивости).
    max_rank = max(ranks.values())
    importance = {c: (max_rank + 0.5) - r for c, r in ranks.items()}

    # Нормируем к 0.75 (доля, оставшаяся после фиксированного financial)
    total_importance = sum(importance.values())
    if total_importance <= 0:
        return dict(DEFAULT_CRITERION_WEIGHTS)

    consumer_weight_pool = 1.0 - FINANCIAL_WEIGHT_FIXED  # 0.75
    weights = {c: importance[c] / total_importance * consumer_weight_pool
               for c in CRITERION_TO_FACTOR}
    weights['financial'] = FINANCIAL_WEIGHT_FIXED

    return weights


# ─────────────────────────────────────────────────────────────────────────────
# ДЕТЕКТОР ЖАНРА КВЕСТА ПО ДАННЫМ ПАРСИНГА
# ─────────────────────────────────────────────────────────────────────────────

def detect_genre(row) -> str:
    """Определяет жанр квеста по содержимому колонок 'Категории', 'Уровень страха'.

    Возвращает один из KNOWN_GENRES или 'Прочее'.
    Использует приоритетную логику: сначала ловим хоррор (доминирующий),
    затем менее частые жанры. Один квест может иметь несколько меток —
    выбираем самую характерную.
    """
    cats_str = str(row.get('Категории', '')).lower()
    fear     = str(row.get('Уровень страха', '')).lower()

    cats = {c.strip() for c in cats_str.split(',')}

    # Хоррор: маркер «Хоррор», «Страшные», «Квест-ужасы», «Кошмары» в категориях
    # ИЛИ уровень страха «очень страшный» / «страшный»
    horror_markers = {'хоррор', 'страшные', 'квест-ужасы', 'кошмары',
                       'паранормальные явления', 'призраки', 'демоны'}
    if any(m in cats_str for m in horror_markers) or 'страшный' in fear and 'не страшный' not in fear:
        return 'Хоррор'

    # Детектив / расследование
    if any(c in cats_str for c in ['детектив', 'расследования', 'преступления']):
        return 'Детектив'

    # Логический
    if any(c in cats_str for c in ['логические квесты', 'головоломки']):
        return 'Логический'

    # Фантастика
    if any(c in cats_str for c in ['научная фантастика', 'космос', 'будущее',
                                    'параллельные миры', 'антиутопия']):
        return 'Фантастика'

    # Мистика / фэнтези
    if any(c in cats_str for c in ['мистические', 'магия', 'фэнтези',
                                    'древние легенды', 'ритуалы', 'культы']):
        return 'Мистика'

    # Исторический
    if any(c in cats_str for c in ['исторические', 'средневековье', 'ссср',
                                    'военный', 'реальные события и люди']):
        return 'Исторический'

    # Приключения
    if any(c in cats_str for c in ['приключения', 'выживание', 'спасение мира',
                                    'ограбления']):
        return 'Приключение'

    return 'Прочее'


def add_genre_column(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет в датафрейм колонку 'жанр' (для удобства подсчётов)."""
    if 'жанр' not in df.columns:
        df = df.copy()
        df['жанр'] = df.apply(detect_genre, axis=1)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# СТРУКТУРЫ ДАННЫХ
# ─────────────────────────────────────────────────────────────────────────────

VerdictColor = Literal['green', 'yellow', 'red']


@dataclass
class ProjectInput:
    """Гипотеза инвестора о новом проекте."""
    lat: float
    lon: float
    metro_station: Optional[str] = None

    quest_type: str = 'Квест-Перформанс'   # Тип механики (с актёрами / без)
    genre: str = 'Хоррор'                   # Жанровое позиционирование

    slot_price: float = 5500
    team_size: int = 6

    capex: float = 4_500_000
    opex_monthly: float = 390_000
    slots_per_day: int = 6
    work_days_per_month: int = 30


@dataclass
class CriterionScore:
    name: str
    score: float
    weight: float
    explanation: str
    metrics: dict = field(default_factory=dict)

    @property
    def color(self) -> str:
        if self.score >= 7: return 'green'
        if self.score >= 4: return 'yellow'
        return 'red'

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class ProjectScore:
    input:        ProjectInput
    criteria:     list[CriterionScore]
    total:        float
    verdict:      VerdictColor
    verdict_text: str
    blockers:     list[str] = field(default_factory=list)

    @property
    def has_blockers(self) -> bool:
        return len(self.blockers) > 0


@dataclass
class Improvement:
    """Одно одиночное предложение по улучшению."""
    parameter: str           # 'location' | 'price' | 'capex' | 'opex'
    description: str
    new_value: str
    new_total_score: float
    delta: float
    new_input: ProjectInput


@dataclass
class Strategy:
    """Комбинированная стратегия — несколько правок применённых вместе.

    Используется для генерации трёх «уровней радикальности»:
        - минимальная коррекция (1 правка)
        - сбалансированная (2 правки)
        - полная переработка (3+ правок)
    """
    label: str                              # 'Минимальная коррекция' и т.п.
    summary: str                            # человекочитаемое описание
    changes: list[str]                      # ['location', 'price'] — что меняли
    change_descriptions: list[str]          # списком, для UI
    new_input: ProjectInput
    new_score: ProjectScore
    delta: float                            # прирост к итоговому скору


# ─────────────────────────────────────────────────────────────────────────────
# ГЕОГРАФИЯ И ПРОГНОЗ ЗАПОЛНЯЕМОСТИ
# ─────────────────────────────────────────────────────────────────────────────

def neighbors_in_radius(lat: float, lon: float, df: pd.DataFrame,
                        radius_km: float) -> pd.DataFrame:
    """Возвращает квесты в радиусе radius_km от точки (lat, lon) — векторно."""
    lats = df['lat'].values
    lons = df['lon'].values
    dlat_km = (lats - lat) * 111.0
    dlon_km = (lons - lon) * 111.0 * math.cos(math.radians(lat))
    dists = (dlat_km**2 + dlon_km**2) ** 0.5
    return df[dists <= radius_km].copy()


def predict_occupancy(lat: float, lon: float, quest_type: str,
                       df: pd.DataFrame) -> tuple[float, str]:
    """Прогноз заполняемости для новой локации.

    Логика (от точного к грубому):
        1. ≥ 3 соседа того же типа в радиусе 1 км → среднее по ним
        2. ≥ 3 соседа любого типа в радиусе 1 км → среднее по ним
        3. ≥ 5 квестов того же типа в Москве   → среднее по ним
        4. иначе → общерыночное среднее
    """
    neighbors = neighbors_in_radius(lat, lon, df, NEIGHBOR_RADIUS_KM)

    same_type_neighbors = neighbors[neighbors['Тип квеста'] == quest_type]
    if len(same_type_neighbors) >= 3:
        return (float(same_type_neighbors['заполняемость'].mean()),
                f"среднее по {len(same_type_neighbors)} {quest_type} в радиусе {NEIGHBOR_RADIUS_KM} км")

    if len(neighbors) >= 3:
        return (float(neighbors['заполняемость'].mean()),
                f"среднее по {len(neighbors)} соседям в радиусе {NEIGHBOR_RADIUS_KM} км")

    same_type_all = df[df['Тип квеста'] == quest_type]
    if len(same_type_all) >= 5:
        return (float(same_type_all['заполняемость'].mean()),
                f"среднее по {len(same_type_all)} квестам типа «{quest_type}» в Москве")

    return (float(df['заполняемость'].mean()), "общерыночное среднее")


# ─────────────────────────────────────────────────────────────────────────────
# КРИТЕРИЙ 1: КОНКУРЕНТНАЯ ПЛОТНОСТЬ
# ─────────────────────────────────────────────────────────────────────────────

def score_competition(inp: ProjectInput, df: pd.DataFrame,
                       weight: float = None) -> CriterionScore:
    nearby = neighbors_in_radius(inp.lat, inp.lon, df, COMPETITION_RADIUS_KM)
    n_total = len(nearby)

    # Балл — по общему числу конкурентов в радиусе
    if n_total == 0:
        base = 10.0
        verdict = "конкурентов в радиусе нет"
    elif n_total <= 2:
        base = 8.0
        verdict = "умеренная конкуренция"
    elif n_total <= 5:
        base = 6.0
        verdict = "заметная конкуренция"
    elif n_total <= 9:
        base = 3.0
        verdict = "плотная конкуренция"
    else:
        base = 1.0
        verdict = "перенасыщенная зона"

    # Топ-3 зон концентрации в Москве — для контекста в пояснении
    top_metros = df['Метро_чистое'].value_counts().head(3) if 'Метро_чистое' in df.columns else None
    is_in_top3 = False
    top3_text = ""
    if top_metros is not None and inp.metro_station:
        if inp.metro_station in top_metros.index:
            is_in_top3 = True
            top3_text = (f" Локация входит в топ-3 самых перенасыщенных зон Москвы "
                         f"({', '.join(top_metros.index[:3])}).")

    explanation = (
        f"В радиусе {COMPETITION_RADIUS_KM*1000:.0f} м от выбранной точки "
        f"расположено **{n_total}** активных квест-комнат. "
        f"Оценка: {verdict}.{top3_text}"
    )

    return CriterionScore(
        name='Конкурентная плотность',
        score=base,
        weight=weight if weight is not None else DEFAULT_CRITERION_WEIGHTS['competition'],
        explanation=explanation,
        metrics={
            'n_total':   int(n_total),
            'radius_km': COMPETITION_RADIUS_KM,
            'is_in_top3': is_in_top3,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# КРИТЕРИЙ 2: СООТВЕТСТВИЕ ЦЕНЫ СПРОСУ
# ─────────────────────────────────────────────────────────────────────────────

def score_price_demand_fit(inp: ProjectInput, df: pd.DataFrame,
                            survey: SurveyMetrics,
                            weight: float = None) -> CriterionScore:
    p_user           = inp.slot_price
    p_market_median  = float(df['цена_руб'].median())
    p_max_median     = survey.price_max_median
    p_refuse_median  = survey.price_refuse_median
    acceptable_share = survey.acceptable_share(p_user)

    if acceptable_share >= 0.80:
        base = 10.0
    elif acceptable_share >= 0.60:
        base = 8.0
    elif acceptable_share >= 0.40:
        base = 6.0
    elif acceptable_share >= 0.20:
        base = 4.0
    elif acceptable_share >= 0.10:
        base = 2.0
    else:
        base = 1.0

    market_diff = (p_user - p_market_median) / p_market_median
    if market_diff > 0.30:
        market_note = (f"Цена выше медианы рынка ({p_market_median:,.0f} ₽) на "
                       f"{market_diff*100:.0f}% — премиум-позиционирование.")
    elif market_diff < -0.20:
        market_note = (f"Цена ниже медианы рынка ({p_market_median:,.0f} ₽) на "
                       f"{abs(market_diff)*100:.0f}% — конкурентное преимущество.")
    else:
        market_note = (f"Цена близка к медиане рынка ({p_market_median:,.0f} ₽) — "
                       f"стандартное позиционирование.")

    explanation = (
        f"При цене **{p_user:,.0f} ₽** проект приемлем для **{acceptable_share*100:.0f}%** "
        f"опрошенной аудитории (медиана готовности платить: **{p_max_median:,.0f} ₽**, "
        f"медиана цены отказа: **{p_refuse_median:,.0f} ₽**). {market_note}"
    )

    return CriterionScore(
        name='Соответствие цены спросу',
        score=base,
        weight=weight if weight is not None else DEFAULT_CRITERION_WEIGHTS['price_fit'],
        explanation=explanation,
        metrics={
            'price_user': p_user,
            'market_median': p_market_median,
            'survey_max_median': p_max_median,
            'survey_refuse_median': p_refuse_median,
            'acceptable_share': acceptable_share,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# КРИТЕРИЙ 3: КОНКУРЕНТНАЯ СРЕДА
# ─────────────────────────────────────────────────────────────────────────────
# Оценивает «силу» окружения, в которое входит новый проект.
# Метрика — медианное число оценок (кол_оценок) у конкурентов в радиусе 900 м.
# Это эмпирический прокси для рыночной зрелости и узнаваемости конкурентов:
# квест с 1500 оценок — заметный бренд, к нему уже идут; квест с 50 оценок —
# нишевое предложение. Чем сильнее конкуренты — тем труднее новому проекту
# отбирать у них клиентов.
# Применяется поправка на количество соседей: при малой выборке (1–2 квеста)
# балл сдвигается ближе к нейтральной середине, при отсутствии конкурентов —
# нейтральная оценка (чтобы не было двойного счёта с критерием 1).

def score_competitor_environment(inp: ProjectInput, df: pd.DataFrame,
                                  survey: SurveyMetrics,
                                  weight: float = None) -> CriterionScore:
    neighbors = neighbors_in_radius(inp.lat, inp.lon, df, COMPETITION_RADIUS_KM)
    n = len(neighbors)

    if n == 0:
        # Нет данных о конкурентах в радиусе — нейтральная оценка.
        # Бонус за отсутствие конкурентов уже учтён в критерии 1.
        base = 6.0
        verdict = "конкурентов в радиусе нет — оценить силу окружения невозможно"
        median_reviews = None
    else:
        # Медиана числа оценок — устойчивая к выбросам мера «силы» соседей
        median_reviews = float(neighbors['кол_оценок'].median())

        # Двухмерная шкала: число конкурентов × их сила
        if n <= 2:
            # Малая выборка — поправка на статистическую неустойчивость
            if median_reviews < 100:
                base, verdict = 9.0, "1–2 слабых конкурента — низкая зрелость локации"
            elif median_reviews < 500:
                base, verdict = 6.0, "1–2 заметных конкурента — средняя сила окружения"
            else:
                base, verdict = 3.0, "1–2 сильных конкурента (бренды) — трудно отбирать клиентов"
        else:
            # Достаточная выборка для устойчивой оценки
            if median_reviews < 100:
                base, verdict = 8.0, "много слабых конкурентов — есть шанс вытеснить нишевых игроков"
            elif median_reviews < 500:
                base, verdict = 5.0, "конкуренты средней силы — рынок зрелый, но без явных лидеров"
            else:
                base, verdict = 2.0, "конкуренты — узнаваемые бренды, входить в зону тяжело"

    if median_reviews is not None:
        explanation = (
            f"В радиусе {COMPETITION_RADIUS_KM*1000:.0f} м расположено **{n}** "
            f"конкурентов; медианное число оценок у них — **{median_reviews:.0f}** "
            f"(показатель рыночной зрелости и узнаваемости). {verdict.capitalize()}."
        )
    else:
        explanation = (
            f"В радиусе {COMPETITION_RADIUS_KM*1000:.0f} м конкурентов нет — "
            f"оценить силу окружения по имеющимся данным невозможно. "
            f"Бонус за отсутствие конкурентов уже учтён в критерии «Конкурентная плотность»."
        )

    return CriterionScore(
        name='Конкурентная среда',
        score=base,
        weight=weight if weight is not None else DEFAULT_CRITERION_WEIGHTS['comp_env'],
        explanation=explanation,
        metrics={
            'n_competitors':  n,
            'median_reviews': median_reviews,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# КРИТЕРИЙ 4: ФИНАНСОВАЯ ЖИЗНЕСПОСОБНОСТЬ
# ─────────────────────────────────────────────────────────────────────────────

def score_financial(inp: ProjectInput, df: pd.DataFrame,
                     weight: float = None) -> tuple[CriterionScore, list[str]]:
    blockers: list[str] = []

    occupancy, occ_source = predict_occupancy(inp.lat, inp.lon, inp.quest_type, df)

    revenue_monthly = inp.slot_price * inp.slots_per_day * occupancy * inp.work_days_per_month
    profit_monthly  = revenue_monthly - inp.opex_monthly
    payback_months  = inp.capex / profit_monthly if profit_monthly > 0 else float('inf')
    roi_year        = ((profit_monthly * 12 - inp.capex) / inp.capex) * 100

    if profit_monthly <= 0:
        base = 1.0
        verdict = "проект убыточен на прогнозной заполняемости"
        if FINANCIAL_LOSS_BLOCKER:
            blockers.append(
                f"Финансовый блокер: проект убыточен (прибыль/мес = {profit_monthly:,.0f} ₽) "
                f"при прогнозной заполняемости {occupancy:.0%}"
            )
    elif payback_months <= 12:
        base = 10.0
        verdict = "быстрая окупаемость, высокая привлекательность"
    elif payback_months <= 18:
        base = 8.0
        verdict = "хорошая окупаемость"
    elif payback_months <= 24:
        base = 6.0
        verdict = "приемлемая окупаемость"
    elif payback_months <= 36:
        base = 4.0
        verdict = "длительная окупаемость, риски ликвидности"
    else:
        base = 2.0
        verdict = f"окупаемость превышает {FINANCIAL_PAYBACK_BLOCKER_MONTHS} мес — высокий риск"
        blockers.append(
            f"Финансовый блокер: прогнозная окупаемость {payback_months:.1f} мес "
            f"превышает порог {FINANCIAL_PAYBACK_BLOCKER_MONTHS} мес"
        )

    payback_str = f"{payback_months:.1f} мес." if payback_months != float('inf') else "не окупается"

    explanation = (
        f"Прогнозная заполняемость для данной локации и типа: "
        f"**{occupancy:.0%}** ({occ_source}). "
        f"При указанных параметрах: выручка/мес = **{revenue_monthly:,.0f} ₽**, "
        f"прибыль/мес = **{profit_monthly:,.0f} ₽**, окупаемость = **{payback_str}**, "
        f"ROI 1-го года = **{roi_year:+.1f}%**. {verdict.capitalize()}."
    )

    return CriterionScore(
        name='Финансовая жизнеспособность',
        score=base,
        weight=weight if weight is not None else DEFAULT_CRITERION_WEIGHTS['financial'],
        explanation=explanation,
        metrics={
            'predicted_occupancy': occupancy,
            'occupancy_source':    occ_source,
            'revenue_monthly':     revenue_monthly,
            'profit_monthly':      profit_monthly,
            'payback_months':      payback_months,
            'roi_year':            roi_year,
        },
    ), blockers


# ─────────────────────────────────────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ ОЦЕНКИ
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_project(inp: ProjectInput, df: pd.DataFrame,
                      survey: SurveyMetrics) -> ProjectScore:
    """Полный прогон проекта через 4 критерия + расчёт итогового вердикта.

    Веса критериев вычисляются динамически через compute_weights(survey)
    на основе рангов факторов выбора из опроса. Если опрос недоступен —
    используются DEFAULT_CRITERION_WEIGHTS.
    """
    weights = compute_weights(survey)

    c1 = score_competition(inp, df, weight=weights['competition'])
    c2 = score_price_demand_fit(inp, df, survey, weight=weights['price_fit'])
    c3 = score_competitor_environment(inp, df, survey, weight=weights['comp_env'])
    c4, blockers = score_financial(inp, df, weight=weights['financial'])

    criteria = [c1, c2, c3, c4]
    total = sum(c.weighted for c in criteria)

    if blockers:
        verdict: VerdictColor = 'red'
        verdict_text = "Не рекомендуется. Финансовая модель содержит блокирующие риски."
    elif total >= VERDICT_GREEN_THRESHOLD:
        verdict = 'green'
        verdict_text = "Рекомендуется к запуску. Проект имеет высокий потенциал."
    elif total >= VERDICT_YELLOW_THRESHOLD:
        verdict = 'yellow'
        verdict_text = "Требует доработки. Существенные риски по отдельным параметрам."
    else:
        verdict = 'red'
        verdict_text = "Не рекомендуется. Ключевые риски делают окупаемость маловероятной."

    return ProjectScore(
        input=inp, criteria=criteria, total=total,
        verdict=verdict, verdict_text=verdict_text, blockers=blockers,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ОДИНОЧНЫЕ РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ
# ─────────────────────────────────────────────────────────────────────────────

def _candidate_locations(df: pd.DataFrame, n: int = 5,
                          radius_km: float = COMPETITION_RADIUS_KM) -> list[MetroStation]:
    """Список станций без конкурентов в радиусе. Использует справочник метро.

    ВАЖНО: исключаем станции внутри Садового кольца. Это компенсация ограниченного
    датасета (топ-100 квестов): «свободные» центральные станции — артефакт
    выборки. На полном датасете центр будет занят, и фильтр можно снять.
    """
    quiet = find_quiet_stations(df, radius_km=radius_km, max_competitors=0,
                                 exclude_central=True)
    return [s for s, _ in quiet[:n]]


def _candidate_prices(inp: ProjectInput, df: pd.DataFrame,
                       survey: SurveyMetrics) -> list[float]:
    """Альтернативные цены: медиана рынка, медиана готовности платить."""
    candidates = []
    market_median   = round(float(df['цена_руб'].median()) / 100) * 100
    survey_comfort  = round(survey.price_max_median / 100) * 100

    for cand in [market_median, survey_comfort]:
        if abs(cand - inp.slot_price) >= 500:
            candidates.append(float(cand))
    return candidates


def suggest_improvements(inp: ProjectInput, df: pd.DataFrame,
                          survey: SurveyMetrics, base_score: ProjectScore,
                          max_suggestions: int = 8) -> list[Improvement]:
    """Перебирает «правдоподобные» одиночные альтернативы по каждому критерию,
    пересчитывает скор, возвращает топ-N с наибольшим приростом.

    Источники альтернатив:
        location — справочник метро (не из датасета!), станции без конкурентов
        price    — медиана рынка / медиана комфорта аудитории
        capex    — снижение через более скромный ремонт
        opex     — снижение через компактное помещение
    """
    suggestions: list[Improvement] = []

    # ── Локации (из справочника метро, а не датасета) ─────────────────────
    for station in _candidate_locations(df, n=5):
        new_inp, opex_note = _clone_with_location(inp, station)
        new_score = evaluate_project(new_inp, df, survey)
        delta = new_score.total - base_score.total
        if delta > 0.3:
            description = (f"Сменить локацию на станцию метро «{station.name}» "
                           f"(линия: {station.line}, без конкурентов в радиусе 900 м)")
            if opex_note:
                description += f". {opex_note}"
            suggestions.append(Improvement(
                parameter='location',
                description=description,
                new_value=station.name,
                new_total_score=new_score.total,
                delta=delta,
                new_input=new_inp,
            ))

    # ── Цены ──────────────────────────────────────────────────────────────
    for new_price in _candidate_prices(inp, df, survey):
        new_inp = _clone_with(inp, slot_price=new_price)
        new_score = evaluate_project(new_inp, df, survey)
        delta = new_score.total - base_score.total
        if delta > 0.3:
            direction = "Снизить" if new_price < inp.slot_price else "Поднять"
            target_label = ("медианы рынка" if abs(new_price - float(df['цена_руб'].median())) < 500
                            else "медианы готовности платить (по опросу)")
            suggestions.append(Improvement(
                parameter='price',
                description=f"{direction} цену с {inp.slot_price:,.0f} ₽ "
                            f"до {new_price:,.0f} ₽ — уровень {target_label}",
                new_value=f"{new_price:,.0f} ₽",
                new_total_score=new_score.total,
                delta=delta,
                new_input=new_inp,
            ))

    # ── CapEx: уменьшение через скромный ремонт ───────────────────────────
    # Предлагаем только если CapEx исходно достаточно высокий (≥ 3 млн —
    # имеет смысл сокращать). Два уровня: -25% и -40%.
    if inp.capex >= 3_000_000:
        for ratio, label in [(0.75, "скромного ремонта и базовых декораций"),
                              (0.60, "минимального CapEx (типовой ремонт без иммерсивных декораций)")]:
            new_capex = inp.capex * ratio
            new_inp = _clone_with(inp, capex=new_capex)
            new_score = evaluate_project(new_inp, df, survey)
            delta = new_score.total - base_score.total
            if delta > 0.3:
                suggestions.append(Improvement(
                    parameter='capex',
                    description=f"Снизить CapEx с {inp.capex:,.0f} ₽ до {new_capex:,.0f} ₽ "
                                f"(–{(1-ratio)*100:.0f}%) за счёт {label}",
                    new_value=f"{new_capex:,.0f} ₽",
                    new_total_score=new_score.total,
                    delta=delta,
                    new_input=new_inp,
                ))
                break  # достаточно одной CapEx-правки

    # ── OpEx: уменьшение через меньшее помещение ──────────────────────────
    # Предлагаем -15% (компактное помещение, меньший ФОТ за счёт совмещения ролей)
    if inp.opex_monthly >= 250_000:
        new_opex = inp.opex_monthly * 0.85
        new_inp = _clone_with(inp, opex_monthly=new_opex)
        new_score = evaluate_project(new_inp, df, survey)
        delta = new_score.total - base_score.total
        if delta > 0.3:
            suggestions.append(Improvement(
                parameter='opex',
                description=f"Снизить OpEx с {inp.opex_monthly:,.0f} ₽/мес "
                            f"до {new_opex:,.0f} ₽/мес (–15%) за счёт более компактного "
                            f"помещения и совмещения ролей в штате",
                new_value=f"{new_opex:,.0f} ₽/мес",
                new_total_score=new_score.total,
                delta=delta,
                new_input=new_inp,
            ))

    suggestions.sort(key=lambda s: -s.delta)
    return suggestions[:max_suggestions]


# ─────────────────────────────────────────────────────────────────────────────
# КОМБИНИРОВАННЫЕ СТРАТЕГИИ (greedy)
# ─────────────────────────────────────────────────────────────────────────────

def suggest_combined_strategy(inp: ProjectInput, df: pd.DataFrame,
                               survey: SurveyMetrics,
                               base_score: ProjectScore) -> list[Strategy]:
    """Жадный поиск трёх стратегий разной радикальности.

    На каждом шаге пробует все одиночные правки по 3 параметрам (location,
    price, genre) поверх текущего состояния, выбирает ту, что даёт максимальный
    прирост к скору. После 1, 2 и 3 итераций фиксирует «уровни радикальности».

    На каждом шаге параметр, уже применённый ранее, исключается из перебора —
    нет смысла менять локацию дважды.
    """
    strategies: list[Strategy] = []
    current_inp = inp
    current_score = base_score
    used_params: set[str] = set()
    cumulative_descriptions: list[str] = []

    LABELS = ['Минимальная коррекция', 'Сбалансированная коррекция',
              'Полная переработка', 'Глубокая переработка']

    for step in range(4):
        # Перебираем все правки, исключая те, что уже применены
        improvements = suggest_improvements(current_inp, df, survey, current_score,
                                             max_suggestions=20)
        improvements = [i for i in improvements if i.parameter not in used_params]

        if not improvements:
            break

        best = improvements[0]  # уже отсортированы по delta

        # Прирост слишком мал — нет смысла продолжать
        if best.delta < 0.3:
            break

        used_params.add(best.parameter)
        cumulative_descriptions.append(best.description)
        current_inp = best.new_input
        current_score = evaluate_project(current_inp, df, survey)

        # Сохраняем стратегию этого уровня
        delta_from_base = current_score.total - base_score.total
        strategies.append(Strategy(
            label=LABELS[step] if step < len(LABELS) else f"Уровень {step+1}",
            summary=_strategy_summary(used_params, current_score),
            changes=list(used_params),
            change_descriptions=list(cumulative_descriptions),
            new_input=current_inp,
            new_score=current_score,
            delta=delta_from_base,
        ))

        # Если уже зелёный — можно остановиться раньше
        if current_score.verdict == 'green':
            break

    return strategies


def _strategy_summary(changes: set[str], score: ProjectScore) -> str:
    """Короткое описание стратегии для UI."""
    items = {
        'location': 'локацию',
        'price':    'цену слота',
        'capex':    'CapEx',
        'opex':     'OpEx',
    }
    order = ['location', 'price', 'capex', 'opex']
    changed = [items[c] for c in order if c in changes]
    if len(changed) == 1:
        s = f"Изменить {changed[0]}"
    elif len(changed) == 2:
        s = f"Изменить {changed[0]} и {changed[1]}"
    else:
        s = f"Изменить {', '.join(changed[:-1])} и {changed[-1]}"

    verdict_word = {'green': '«Рекомендуется»', 'yellow': '«Жёлтый»', 'red': '«Не рекомендуется»'}
    return f"{s}. Итог: {score.total:.2f}/10, статус {verdict_word.get(score.verdict, score.verdict)}."


# ─────────────────────────────────────────────────────────────────────────────
# ВНУТРЕННЕЕ
# ─────────────────────────────────────────────────────────────────────────────

def _clone_with(inp: ProjectInput, **changes) -> ProjectInput:
    """Клонировать ProjectInput с заменой нескольких полей."""
    fields = {
        'lat': inp.lat, 'lon': inp.lon, 'metro_station': inp.metro_station,
        'quest_type': inp.quest_type, 'genre': inp.genre,
        'slot_price': inp.slot_price, 'team_size': inp.team_size,
        'capex': inp.capex, 'opex_monthly': inp.opex_monthly,
        'slots_per_day': inp.slots_per_day,
        'work_days_per_month': inp.work_days_per_month,
    }
    fields.update(changes)
    return ProjectInput(**fields)


# ─────────────────────────────────────────────────────────────────────────────
# АВТОКОРРЕКЦИЯ OPEX ПО ЗОНЕ АРЕНДЫ
# ─────────────────────────────────────────────────────────────────────────────

# Допущения о структуре OpEx (используются для автокоррекции при смене локации):
# - аренда составляет ~45% OpEx;
# - остальные 55% (ФОТ, маркетинг, прочее) от локации не зависят.
RENT_SHARE_OF_OPEX = 0.45


def _adjust_opex_for_location(old_opex: float,
                               old_lat: float, old_lon: float,
                               new_lat: float, new_lon: float) -> tuple[float, str]:
    """Корректирует OpEx при смене локации с учётом разницы коэф. аренды.

    Returns:
        (new_opex, объяснение_изменения)
    """
    _, old_coef, _ = get_rent_zone(old_lat, old_lon)
    _, new_coef, new_zone = get_rent_zone(new_lat, new_lon)

    if abs(old_coef - new_coef) < 0.01:
        return old_opex, ""  # та же зона

    # Разделяем OpEx на «аренда» и «всё остальное»
    rent_part  = old_opex * RENT_SHARE_OF_OPEX
    other_part = old_opex - rent_part
    new_rent   = rent_part * (new_coef / old_coef)
    new_opex   = new_rent + other_part

    delta = new_opex - old_opex
    if abs(delta) < 1000:
        return old_opex, ""

    direction = "снижается" if delta < 0 else "вырастает"
    note = (f"OpEx {direction} с {old_opex:,.0f} ₽ до {new_opex:,.0f} ₽ "
            f"(на {abs(delta):,.0f} ₽) с учётом разницы аренды в зоне «{new_zone}» "
            f"(коэф. ×{new_coef} против ×{old_coef})")
    return new_opex, note


def _clone_with_location(inp: ProjectInput, station: MetroStation) -> tuple[ProjectInput, str]:
    """Клонирование при смене локации — с автокоррекцией OpEx."""
    new_opex, note = _adjust_opex_for_location(
        inp.opex_monthly, inp.lat, inp.lon, station.lat, station.lon
    )
    return _clone_with(inp, lat=station.lat, lon=station.lon,
                       metro_station=station.name,
                       opex_monthly=new_opex), note

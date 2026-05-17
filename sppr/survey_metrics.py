"""
survey_metrics.py — извлечение количественных параметров из опроса
целевой аудитории для использования в скоринговом движке СППР.

Опрос загружается из Excel-файла. Если файл недоступен, используются
референсные значения, полученные на полной выборке исследования.

Главные функции:
    load_survey_metrics(path) -> SurveyMetrics
    SurveyMetrics             — dataclass со всеми метриками для скоринга
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Референсные значения метрик опроса (N = 154, апрель–май 2026).
# Используются, если файл опроса по какой-то причине недоступен —
# логика скоринга остаётся работоспособной.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_PRICE_MAX_MEDIAN     = 5600.0   # медиана «макс готовности платить», ₽
DEFAULT_PRICE_REFUSE_MEDIAN  = 9500.0   # медиана «цена отказа», ₽
DEFAULT_RESPONDENTS          = 154

# Распределение спроса по жанрам (доля респондентов, выбравших жанр).
# Сумма может превышать 1, т.к. вопрос multi-select.
DEFAULT_GENRE_DEMAND = {
    'Хоррор':            0.4935,
    'Квест-Перформанс':  0.4286,
    'Логический':        0.4286,
    'Детектив':          0.3247,
    'Приключение':       0.1169,
    'Мистика':           0.0260,
    'Фантастика':        0.0000,
    'Исторический':      0.0000,
}

# Средние ранги факторов выбора (1 = самый важный, 6 = наименее важный).
DEFAULT_FACTOR_RANKS = {
    'Жанр':            3.05,
    'Локация':         3.27,
    'Цена':            3.44,
    'Актёры':          3.45,
    'Отзывы знакомых': 3.58,
}


# ─────────────────────────────────────────────────────────────────────────────
# Маппинг названий жанров из опроса → к названиям типов в датасете парсинга.
# Опрос оперирует поджанрами (хоррор, детектив), парсинг — типами квестов
# (Квест-Перформанс, Квест, Экшн-игра, Хоррор-кинотеатр).
# Согласование делается по лучшей семантической близости.
# ─────────────────────────────────────────────────────────────────────────────

GENRE_TO_TYPE_MAP = {
    # Опрос → парсинг (один-в-один или приближённое соответствие)
    'Хоррор':            'Квест-Перформанс',     # 89% перформансов — это хорроры
    'Квест-Перформанс':  'Квест-Перформанс',
    'Логический':        'Квест',
    'Детектив':          'Квест',
    'Приключение':       'Квест',
    'Экшн':              'Экшн-игра',
    'Хоррор-кинотеатр':  'Хоррор-кинотеатр',
}


@dataclass
class SurveyMetrics:
    """Параметры опроса, нужные для скорингового движка.

    Если поле = None / 0 — соответствующий критерий скоринга использует
    референсные значения.
    """

    n_respondents: int = DEFAULT_RESPONDENTS

    # Ценовые метрики (₽)
    price_max_median:    float = DEFAULT_PRICE_MAX_MEDIAN
    price_refuse_median: float = DEFAULT_PRICE_REFUSE_MEDIAN
    price_max_values:    list = field(default_factory=list)  # для расчёта acceptable_share

    # Спрос по жанрам (доля респондентов)
    genre_demand: dict = field(default_factory=lambda: dict(DEFAULT_GENRE_DEMAND))

    # Ранги факторов выбора (1 = самый важный)
    factor_ranks: dict = field(default_factory=lambda: dict(DEFAULT_FACTOR_RANKS))

    source: str = 'defaults'   # 'defaults' | 'survey'

    def acceptable_share(self, price: float) -> float:
        """Доля респондентов, для которых указанная цена приемлема.

        Считается как доля ответов, где «макс готовности платить» >= price.
        Если значения по респондентам отсутствуют — используется
        приближение по медиане.
        """
        if self.price_max_values:
            n_ok = sum(1 for p in self.price_max_values if p >= price)
            return n_ok / len(self.price_max_values)
        # Аппроксимация по медиане, когда детальные ответы недоступны
        if price <= self.price_max_median * 0.7:
            return 0.95
        elif price <= self.price_max_median:
            return 0.70
        elif price <= self.price_refuse_median * 0.7:
            return 0.40
        elif price <= self.price_refuse_median:
            return 0.20
        else:
            return 0.05

    def factor_weight(self, factor: str) -> float:
        """Вес фактора в [0; 1]. Чем меньше ранг — тем больше вес."""
        rank = self.factor_ranks.get(factor, 3.5)
        return (7 - rank) / 6


# ─────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА ИЗ EXCEL
# ─────────────────────────────────────────────────────────────────────────────

def load_survey_metrics(path: Optional[str] = None) -> SurveyMetrics:
    """Загружает метрики опроса из Excel-файла.

    Если файл недоступен — возвращает SurveyMetrics с референсными
    значениями, чтобы скоринг оставался работоспособным.
    """
    if path is None or not os.path.exists(path):
        return SurveyMetrics()  # all defaults

    try:
        df = pd.read_excel(path)
    except Exception:
        return SurveyMetrics()

    n = len(df)

    # ── Ценовые метрики (столбцы 11, 12 формы) ──────────────────────────────
    # pd.to_numeric с errors='coerce' преобразует свободные ответы вроде
    # «не знаю» в NaN, чтобы они не ломали расчёт медианы.
    try:
        price_max_series    = pd.to_numeric(df.iloc[:, 11], errors='coerce').dropna()
        price_refuse_series = pd.to_numeric(df.iloc[:, 12], errors='coerce').dropna()
        price_max_values    = price_max_series.tolist()
        price_max_median    = (float(price_max_series.median())
                                if len(price_max_series) else DEFAULT_PRICE_MAX_MEDIAN)
        price_refuse_median = (float(price_refuse_series.median())
                                if len(price_refuse_series) else DEFAULT_PRICE_REFUSE_MEDIAN)
    except (KeyError, IndexError):
        price_max_values    = []
        price_max_median    = DEFAULT_PRICE_MAX_MEDIAN
        price_refuse_median = DEFAULT_PRICE_REFUSE_MEDIAN

    # ── Спрос по жанрам (столбец 8) ─────────────────────────────────────────
    genre_demand = _parse_genre_demand(df, n)

    # ── Ранги факторов выбора (столбцы 17–21) ───────────────────────────────
    factor_ranks = _parse_factor_ranks(df)

    return SurveyMetrics(
        n_respondents       = n,
        price_max_median    = price_max_median,
        price_refuse_median = price_refuse_median,
        price_max_values    = price_max_values,
        genre_demand        = genre_demand,
        factor_ranks        = factor_ranks,
        source              = 'survey',
    )


def _parse_genre_demand(df: pd.DataFrame, n: int) -> dict:
    """Доля респондентов, выбравших каждый жанр.

    Вопрос multi-select: ответы хранятся строкой через запятую, поэтому
    распознавание идёт по характерным ключевым словам.
    """
    if n == 0:
        return dict(DEFAULT_GENRE_DEMAND)

    try:
        col = df.iloc[:, 8].dropna().astype(str)
    except (KeyError, IndexError):
        return dict(DEFAULT_GENRE_DEMAND)

    keywords = {
        'Хоррор':           ['хоррор', 'страшн', 'ужас'],
        'Квест-Перформанс': ['перформанс', 'актёр', 'актер'],
        'Логический':       ['логическ', 'головоломк'],
        'Детектив':         ['детектив', 'расследован'],
        'Приключение':      ['приключен'],
        'Мистика':          ['мистик'],
        'Фантастика':       ['фантастик'],
        'Исторический':     ['историч'],
    }

    counts = {g: 0 for g in keywords}
    for response in col:
        lower = response.lower()
        for genre, kws in keywords.items():
            if any(kw in lower for kw in kws):
                counts[genre] += 1

    # Доля считается от всех респондентов, а не только от ответивших на вопрос —
    # нас интересует охват целевой аудитории.
    return {g: c / n for g, c in counts.items()}


def _parse_factor_ranks(df: pd.DataFrame) -> dict:
    """Средние ранги факторов выбора (столбцы 17–21)."""
    factor_cols = {
        'Цена':            17,
        'Жанр':            18,
        'Локация':         19,
        'Отзывы знакомых': 20,
        'Актёры':          21,
    }
    ranks = {}
    for factor, idx in factor_cols.items():
        try:
            series = pd.to_numeric(df.iloc[:, idx], errors='coerce').dropna()
            if len(series) > 0:
                ranks[factor] = float(series.mean())
            else:
                ranks[factor] = DEFAULT_FACTOR_RANKS[factor]
        except (KeyError, IndexError):
            ranks[factor] = DEFAULT_FACTOR_RANKS[factor]
    return ranks


if __name__ == '__main__':
    # Smoke test
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'survey.xlsx'
    m = load_survey_metrics(path)
    print(f"Источник: {m.source}, респондентов: {m.n_respondents}")
    print(f"Медиана готовности платить: {m.price_max_median:,.0f} ₽")
    print(f"Медиана цены отказа:        {m.price_refuse_median:,.0f} ₽")
    print(f"Спрос по жанрам:")
    for g, d in sorted(m.genre_demand.items(), key=lambda x: -x[1]):
        print(f"   {g:20s}: {d:.1%}")
    print(f"Ранги факторов:")
    for f, r in sorted(m.factor_ranks.items(), key=lambda x: x[1]):
        print(f"   {f:20s}: {r:.2f}")

    print(f"\nДля цены 5000 ₽: приемлемо для {m.acceptable_share(5000):.0%} аудитории")
    print(f"Для цены 7000 ₽: приемлемо для {m.acceptable_share(7000):.0%} аудитории")

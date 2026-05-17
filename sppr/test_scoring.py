"""
test_scoring.py — проверка скорингового движка v2 на сценариях из кейса главы 3.
Включает:
    - 4 сценария (Иван исходный / скорректированный / стресс-тест / идеальный)
    - одиночные рекомендации
    - комбинированные стратегии (3 уровня радикальности)

Запуск:
    cd dashboard_refactor && python3 sppr/test_scoring.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from sppr import (
    ProjectInput,
    evaluate_project, suggest_improvements, suggest_combined_strategy,
    load_survey_metrics, find_station,
    detect_genre,
)
from sppr.scoring import add_genre_column


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

df = pd.read_excel(os.path.join(ROOT, 'mir_kvestov_full.xlsx'))
df['Метро_чистое'] = df['Метро'].str.replace('м. ', '', regex=False).str.strip()
df = add_genre_column(df)

survey = load_survey_metrics(os.path.join(ROOT, 'survey.xlsx'))


# ─────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНАЯ ПЕЧАТЬ
# ─────────────────────────────────────────────────────────────────────────────

VERDICT_SYMBOLS = {'green': '[+]', 'yellow': '[~]', 'red': '[-]'}


def print_score(scenario_name, score):
    print(f"\n{'═' * 78}")
    print(f"СЦЕНАРИЙ: {scenario_name}")
    print(f"{'═' * 78}")
    inp = score.input
    print(f"  Локация: {inp.metro_station or f'({inp.lat:.4f}, {inp.lon:.4f})'}")
    print(f"  Формат:  {inp.quest_type}, жанр: {inp.genre}")
    print(f"  Цена:    {inp.slot_price:,.0f} ₽  |  CapEx: {inp.capex:,.0f}  |  OpEx: {inp.opex_monthly:,.0f}/мес")
    print()
    print(f"  ИТОГ:    {score.total:.2f}/10  {VERDICT_SYMBOLS[score.verdict]} {score.verdict.upper()}")
    print(f"           {score.verdict_text}")

    if score.has_blockers:
        print(f"\n  БЛОКЕРЫ:")
        for b in score.blockers:
            print(f"    !  {b}")

    print(f"\n  Критерии:")
    for c in score.criteria:
        marker = VERDICT_SYMBOLS[c.color]
        print(f"    {marker} {c.name:32s}  {c.score:4.1f}/10  (вес {c.weight:.0%})")


def print_improvements(improvements, label="ОДИНОЧНЫЕ РЕКОМЕНДАЦИИ"):
    print(f"\n  {label}:")
    if not improvements:
        print(f"    (рекомендации не сформированы)")
        return
    for i, imp in enumerate(improvements, 1):
        print(f"    {i}. [{imp.parameter:8s}] {imp.description}")
        print(f"       → {imp.new_total_score:.2f}/10  (+{imp.delta:.2f})")


def print_strategies(strategies):
    print(f"\n  КОМБИНИРОВАННЫЕ СТРАТЕГИИ:")
    if not strategies:
        print(f"    (стратегии не сформированы — текущий проект не поддаётся улучшению)")
        return
    for s in strategies:
        v = VERDICT_SYMBOLS[s.new_score.verdict]
        print(f"\n    {v} {s.label} (+{s.delta:.2f})")
        print(f"       Итог: {s.new_score.total:.2f}/10 ({s.new_score.verdict})")
        for d in s.change_descriptions:
            print(f"       • {d}")


# ─────────────────────────────────────────────────────────────────────────────
# СЦЕНАРИЙ 1: ИСХОДНАЯ ГИПОТЕЗА ИВАНА (плохая, должна получить красный)
# ─────────────────────────────────────────────────────────────────────────────
station = find_station('Бауманская')
ivan_initial = ProjectInput(
    lat=station.lat, lon=station.lon, metro_station=station.name,
    quest_type='Квест-Перформанс', genre='Хоррор',
    slot_price=7000, team_size=8,
    capex=4_500_000, opex_monthly=390_000, slots_per_day=6,
)
score_initial = evaluate_project(ivan_initial, df, survey)
print_score("Исходная гипотеза Ивана (хоррор-перформанс на Бауманской, 7000 ₽)",
            score_initial)

singles = suggest_improvements(ivan_initial, df, survey, score_initial)
print_improvements(singles)

strategies = suggest_combined_strategy(ivan_initial, df, survey, score_initial)
print_strategies(strategies)


# ─────────────────────────────────────────────────────────────────────────────
# СЦЕНАРИЙ 2: СТРЕСС-ТЕСТ — заведомо ужасный проект
# ─────────────────────────────────────────────────────────────────────────────
station = find_station('Партизанская')
stress = ProjectInput(
    lat=station.lat, lon=station.lon, metro_station=station.name,
    quest_type='Квест-Перформанс', genre='Хоррор',
    slot_price=12_000, team_size=6,
    capex=7_000_000, opex_monthly=550_000, slots_per_day=6,
)
score_stress = evaluate_project(stress, df, survey)
print_score("Стресс-тест: премиум-проект на Партизанской", score_stress)
print_strategies(suggest_combined_strategy(stress, df, survey, score_stress))


# ─────────────────────────────────────────────────────────────────────────────
# СЦЕНАРИЙ 3: РЕАЛИСТИЧНО-ХОРОШИЙ ПРОЕКТ
# ─────────────────────────────────────────────────────────────────────────────
station = find_station('Технопарк')  # практически без квестов в радиусе
realistic = ProjectInput(
    lat=station.lat, lon=station.lon, metro_station=station.name,
    quest_type='Квест', genre='Логический',
    slot_price=5500, team_size=4,
    capex=3_500_000, opex_monthly=300_000, slots_per_day=6,
)
score_realistic = evaluate_project(realistic, df, survey)
print_score("Реалистичный проект (логический квест на Технопарке, 5500 ₽)", score_realistic)
print_strategies(suggest_combined_strategy(realistic, df, survey, score_realistic))


# ─────────────────────────────────────────────────────────────────────────────
# СВОДКА
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'═' * 78}")
print(f"СВОДКА:")
print(f"{'═' * 78}")
print(f"  Исходный план Ивана:       {score_initial.total:.2f}/10  ({score_initial.verdict.upper()})")
print(f"  Стресс-тест:               {score_stress.total:.2f}/10  ({score_stress.verdict.upper()})")
print(f"  Реалистичный «нишевый»:    {score_realistic.total:.2f}/10  ({score_realistic.verdict.upper()})")

if strategies:
    best = max(strategies, key=lambda s: s.delta)
    print(f"  Иван после полной переработки: "
          f"{best.new_score.total:.2f}/10  ({best.new_score.verdict.upper()})")
